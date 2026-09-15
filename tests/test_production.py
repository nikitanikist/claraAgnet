import asyncio
import json
import time
import pytest
from fastapi.testclient import TestClient
from clara.config import Config
from clara.store import Store
from clara.workflows import Workflows
from clara.knowledge import Knowledge,Memory
from clara.operations import Operations
from clara.production_tools import definitions
from clara.windows_bridge import choose_window,select_control
from clara.portal import PortalWorker
from test_core import make_pdf


@pytest.fixture
def env(tmp_path):
    cfg=Config(tmp_path/'data');cfg.initialize();store=Store(cfg.data/'test.sqlite')
    cid=store.create_conversation()['id'];job=store.create_job(cid,'Print client copies','autonomous',[])
    return cfg,store,job,Workflows(store,cfg)


def test_knowledge_filters_versions_and_client_namespaces(env):
    cfg,s,j,w=env;k=Knowledge(s)
    k.add('Printing','Print client copies using the current settings.','K04',{'source':'Vendor manual','build':'2025.2','tax_year':'2025'},'client:A')
    k.add('Printing','Print old copies.','K04',{'source':'Old manual','build':'2024.1','tax_year':'2024'},'firm')
    assert k.search('printing',scope_key='client:B',build='2025.2',tax_year='2025')==[]
    matches=k.search('print',scope_key='client:A',build='2025.2',tax_year='2025')
    assert len(matches)==1 and matches[0]['metadata']['source']=='Vendor manual'
    k.retire(matches[0]['id'])
    assert not k.search('print',scope_key='client:A',build='2025.2',tax_year='2025')


def begin(w,j):
    return w.begin(j,'t1-print',{'client_key':'test-a','year':'2025','members':['Test Person']})


def test_workflow_rejects_skipped_stages_wrong_client_and_changed_pdf(env):
    cfg,s,j,w=env;begin(w,j)
    with pytest.raises(ValueError,match='earlier'): w.checkpoint(j,'documents',[])
    make_pdf(cfg.workspace/'test.pdf')
    with pytest.raises(ValueError,match='not part'): w.verify_document(j,'test.pdf','Someone Else','client-copy','2025')


def test_pdf_evidence_checks_identity_and_hash_before_reuse(env):
    cfg,s,j,w=env;begin(w,j)
    p=cfg.workspace/'return.pdf';make_pdf(p,'Test Person income tax return 2025')
    good=w.verify_document(j,str(p),'Test Person','client-copy','2025')
    assert good['verified'] and good['pages']==1
    assert w._proofs(j,[good['id']])
    make_pdf(p,'Another Person income tax return 2025')
    bad=w.verify_document(j,str(p),'Test Person','client-copy','2025')
    assert not bad['verified']
    with pytest.raises(ValueError,match='changed'): w._proofs(j,[good['id']])
    cid=s.create_conversation()['id'];other=s.create_job(cid,'other','ask',[])
    with pytest.raises(ValueError,match='another conversation'): w._proofs(other,[good['id']])


def test_full_closeout_cannot_remove_required_outputs_or_self_approve(env):
    cfg,s,j,w=env
    state=w.begin(j,'t1-closeout',{'client_key':'A','year':'2025','members':['Test Person']},{'documents':[]})
    assert len(state['contract']['documents'])==3
    assert set(state['contract'])=={'intake','source-copy','application','documents','signature-packet','invoice','delivery','review'}
    assert w.finish_check(j).startswith('Workflow incomplete')
    with pytest.raises(ValueError): w.review(j['conversation_id'],'Looks done')
    with pytest.raises(ValueError): w.checkpoint(j,'review',[],status='verified')


def test_verified_print_package_waits_for_operator_and_preserves_progress(env):
    cfg,s,j,w=env;begin(w,j)
    w.checkpoint(j,'intake',[])
    p=cfg.workspace/'return.pdf';make_pdf(p,'Test Person income tax return 2025')
    fs={name:fn for name,desc,schema,fn in definitions(cfg,s,j)}
    copied=asyncio.run(fs['copy_file']({'source':str(p),'destination':'working.pdf'}))
    w.checkpoint(j,'source-copy',[copied['id']])
    app=w.evidence(j,'desktop_assertion','Test application',{'checks':[{'passed':True}]},True)
    w.checkpoint(j,'application',[app['id']])
    proof=w.verify_document(j,str(p),'Test Person','client-copy','2025')
    w.checkpoint(j,'documents',[proof['id']])
    w.checkpoint(j,'review',[proof['id']],status='needs_review')
    assert 'ready for review' in w.finish_check(j)
    reloaded=Workflows(Store(s.path),cfg)
    assert reloaded.snapshot(j['conversation_id'])['stages']['documents']['status']=='verified'
    assert reloaded.review(j['conversation_id'],'Checked PDF identity, pages and output completeness')['status']=='completed'
    assert reloaded.finish_check(j) is None


def test_copy_never_overwrites_previous_run(env):
    cfg,s,j,w=env;p=cfg.workspace/'source';p.write_text('new')
    (cfg.workspace/'dest').write_text('previous')
    copy=next(fn for name,desc,schema,fn in definitions(cfg,s,j) if name=='copy_file')
    with pytest.raises(FileExistsError): asyncio.run(copy({'source':'source','destination':'dest'}))
    assert (cfg.workspace/'dest').read_text()=='previous'


def test_budget_aggregates_resumes_and_marks_unknown_cost(env):
    cfg,s,j,w=env;cfg.save_settings({**cfg.settings(),'max_budget_usd':3});begin(w,j)
    s.execute('UPDATE jobs SET usage=?,status=? WHERE id=?',(json.dumps({'turns':31,'sdk_estimated_usd':2,'wall_duration_ms':9000,'coverage':'reported'}),'failed',j['id']))
    nextjob=s.create_job(j['conversation_id'],'Continue','ask',[]);w.attach(nextjob)
    b=w.remaining(j['conversation_id']);assert b['remaining_turns']==9 and b['remaining_usd']==1
    s.execute('UPDATE jobs SET usage=? WHERE id=?',(json.dumps({'turns':None,'coverage':'partial','wall_duration_ms':1000}),nextjob['id']))
    assert w.remaining(j['conversation_id'])['partial']


def test_memory_needs_review_multiple_cases_and_fresh_conversation(env):
    cfg,s,j,w=env;begin(w,j);m=Memory(s)
    item=m.propose(j,'Print via application dialog','Taxprep','2025.2',{'preconditions':['right client'],'actions':['Print'],'postconditions':['PDF verified']})
    mid=item['id'];m.review(mid,'approve','Procedure contains no client values',share=True)
    assert m.get(mid)['status']=='candidate'
    with pytest.raises(ValueError,match='build'): m.begin_use(j,mid,'2024.1')
    for i in range(3):
        cid=j['conversation_id'] if i<2 else s.create_conversation()['id']
        job=s.create_job(cid,'print','ask',[])
        if i<2: w.attach(job)
        else: w.begin(job,'t1-print',{'client_key':'test-b','year':'2025','members':['Test B']})
        m.begin_use(job,mid,'2025.2')
        path=cfg.workspace/f'result{i}.pdf';person='Test Person' if i<2 else 'Test B'
        make_pdf(path,person+' income tax 2025')
        proof=w.verify_document(job,str(path),person,'client-copy','2025')
        m.validate(job,mid,proof['id'])
        assert m.get(mid)['status']==('qualified' if i==2 else 'provisional')
    assert not m.retrieve(j,'print','Taxprep','2024.1')
    assert m.retrieve(j,'print','Taxprep','2025.2')[0]['reuse_allowed']
    m.review(mid,'suspend','Shortcut failed after application change')
    assert not m.retrieve(j,'print','Taxprep','2025.2')


def test_client_fact_cannot_be_shared_and_scope_cannot_be_read_by_other_client(env):
    cfg,s,j,w=env;begin(w,j);m=Memory(s)
    item=m.propose(j,'Client preference','','',{'note':'Prefers PDF'},kind='client_fact')
    with pytest.raises(ValueError,match='cannot be promoted'): m.review(item['id'],'approve',share=True)
    other=s.create_job(s.create_conversation()['id'],'different','ask',[])
    assert not m.retrieve(other)


def test_uncertain_operation_is_not_reexecuted_after_restart(env):
    cfg,s,j,w=env;begin(w,j);ops=Operations(s)
    first=ops.reserve(j,'pandadoc','create','A-2025-closeout',{'template':'approved'})
    assert first['execute_allowed']
    again=Operations(Store(s.path)).reserve(j,'pandadoc','create','A-2025-closeout',{'template':'approved'})
    assert not again['execute_allowed'] and first['id']==again['id']
    with pytest.raises(ValueError,match='different request'): ops.reserve(j,'pandadoc','create','A-2025-closeout',{'template':'changed'})
    ops.confirm_absence(first['id'],'Checked the actual document list; the draft does not exist.')
    assert ops.reserve(j,'pandadoc','create','A-2025-closeout',{'template':'approved'})['execute_allowed']
    assert not ops.reserve(j,'pandadoc','create','A-2025-closeout',{'template':'approved'})['execute_allowed']
    with pytest.raises(ValueError,match='already used'): ops.confirm_absence(first['id'],'Checked remote records again after the retry.')


def test_reconcile_accepts_canonical_reservation_key_but_not_wrong_system_or_stale_proof(env):
    cfg,s,j,w=env;begin(w,j);ops=Operations(s)
    op=ops.reserve(j,'pandadoc','create_signature_packet','closeout:form-1:pandadoc:m1',{})
    def proof(system,created=None):
        e=w.evidence(j,'remote_record','doc-1',{'system':system,'remote_id':'doc-1','url':'https://app.pandadoc.com/a/#/documents/doc-1',
            'external_key':'Test Person T1 2025 (v2)','reservation_key':'closeout:form-1:pandadoc:m1'},True)
        if created is not None: s.execute('UPDATE evidence SET created=? WHERE id=?',(created,e['id']))
        return e['id']
    with pytest.raises(ValueError,match='does not match'): ops.reconcile(j,op['id'],proof('storage'))
    with pytest.raises(ValueError,match='does not match'): ops.reconcile(j,op['id'],proof('pandadoc',created=op_updated(s,op['id'])-1))
    assert s.one('SELECT state FROM operations WHERE id=?',(op['id'],))['state']=='uncertain'
    good=proof('pandadoc');confirmed=ops.reconcile(j,op['id'],good)
    assert confirmed['state']=='confirmed' and confirmed['remote_id']=='doc-1' and json.loads(confirmed['result'])=={'evidence_id':good}
    assert ops.reconcile(j,op['id'],good)['state']=='confirmed'


def op_updated(s,oid): return s.one('SELECT updated FROM operations WHERE id=?',(oid,))['updated']


def test_ambiguous_windows_and_controls_are_not_silently_chosen():
    windows=[{'title':'Taxprep - A'},{'title':'Taxprep - B'}]
    with pytest.raises(ValueError,match='ambiguous'): choose_window(windows,'Taxprep')
    assert choose_window(windows,'Taxprep - B')['title']=='Taxprep - B'
    with pytest.raises(ValueError,match='ambiguous'): select_control([({'name':'Print'},1),({'name':'Print'},2)],{'name':'Print'})


def test_skill_pack_preserves_operator_edits(env):
    cfg,s,j,w=env;p=cfg.skills/'cpa-t1-closeout'/'SKILL.md';p.write_text('Custom approved instructions')
    cfg.initialize();assert p.read_text()=='Custom approved instructions'


def test_portal_assignment_retries_do_not_duplicate_tasks(env):
    cfg,s,j,w=env
    class Manager:
        active_job=None
        queue=asyncio.Queue()
    m=Manager();worker=PortalWorker(cfg,s,m)
    a={'id':'assignment-one','owner_key':'operator','prompt':'Find the test file'};settings={'owner_key':'operator'}
    first=worker.accept(a,settings);second=worker.accept(a,settings)
    assert first['job_id']==second['job_id'] and m.queue.qsize()==1
    with pytest.raises(ValueError,match='another operator'): worker.accept({**a,'owner_key':'different'},settings)
    with pytest.raises(ValueError,match='different content'): worker.accept({**a,'prompt':'changed'},settings)


def test_backup_restores_database_and_files_without_credentials(env,tmp_path):
    from clara.backup import backup,restore
    import shutil
    cfg,s,j,w=env;begin(w,j)
    (cfg.workspace/'output.txt').write_text('verified output')
    (cfg.data/'chrome-profile').mkdir();(cfg.data/'chrome-profile'/'Cookies').write_text('do not copy')
    archive=backup(cfg,tmp_path/'backups')
    with pytest.raises(ValueError,match='new, empty'): restore(archive,cfg.data)
    saved=tmp_path/'old-data';shutil.move(cfg.data,saved)
    restore(archive,cfg.data)
    assert (cfg.workspace/'output.txt').read_text()=='verified output'
    assert not (cfg.data/'chrome-profile').exists()
    # The test uses test.sqlite; the real database snapshot is tested separately below.
    assert (cfg.data/'settings.json').is_file()


def test_backup_uses_consistent_sqlite_snapshot(env,tmp_path):
    from clara.backup import backup
    import zipfile,sqlite3
    cfg,s,j,w=env;real=Store(cfg.data/'clara.sqlite3');cid=real.create_conversation()['id']
    archive=backup(cfg,tmp_path/'backups')
    with zipfile.ZipFile(archive) as z: data=z.read('clara.sqlite3')
    extracted=tmp_path/'restored.sqlite';extracted.write_bytes(data)
    assert Store(extracted).conversation(cid)['id']==cid


def test_evidence_capture_handles_list_blocks_masks_tokens_and_saves_images(env):
    from clara.evidence import capture
    import base64
    cfg,s,j,w=env
    # A one-pixel PNG; image contents are not copied into exported JSON.
    data=base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'synthetic').decode()
    result=capture(cfg,s,j,{'tool_name':'mcp__windows__Screenshot','tool_response':[
        {'type':'text','text':'Bearer private-token'}, {'type':'image','mimeType':'image/png','data':data}]},'test')
    assert len(result['images'])==1
    row=s.one('SELECT * FROM evidence WHERE id=?',(result['observation_id'],))
    assert 'private-token' not in row['payload'] and data not in row['payload']
    cfg.save_settings({**cfg.settings(),'capture_evidence':False})
    result=capture(cfg,s,j,{'tool_name':'mcp__windows__Screenshot','tool_response':{'content':[{'type':'image','mimeType':'image/png','data':data}]}},'test2')
    assert not result['images']


def test_unavailable_browser_does_not_prevent_desktop_configuration(env,monkeypatch):
    import clara.connectors as c
    cfg,s,j,w=env;cfg.save_settings({**cfg.settings(),'browser_enabled':True,'desktop_enabled':True})
    monkeypatch.setattr(c,'connector_status',lambda cfg:{'browser':{'available':False},'desktop':{'installed':True}})
    monkeypatch.setattr(c,'desktop_ready',lambda:{'ready':True})
    monkeypatch.setattr(c,'desktop_command',lambda:('python',['bridge.py']))
    assert set(c.mcp_connectors(cfg))=={'windows'}


def test_runtime_does_not_mark_incomplete_workflow_completed(env,monkeypatch):
    from clara.agent import AgentManager
    from claude_agent_sdk import ResultMessage
    cfg,s,j,w=env;begin(w,j)
    class SDK:
        def __init__(self,options): self.options=options
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def query(self,prompt): pass
        async def receive_response(self):
            yield ResultMessage(subtype='success',duration_ms=1,duration_api_ms=1,is_error=False,num_turns=1,session_id='synthetic',result='Everything completed.',usage={'input_tokens':10,'output_tokens':10})
    async def auth(): return {'connected':True,'plan':'test'}
    monkeypatch.setattr('clara.agent.ClaudeSDKClient',SDK);monkeypatch.setattr('clara.agent.auth_status',auth)
    asyncio.run(AgentManager(cfg,s).execute(j))
    assert s.job(j['id'])['status']=='incomplete'


def test_operator_api_is_authenticated_and_rejects_premature_workflow_review(tmp_path,monkeypatch):
    from clara.app import create_app
    class Manager:
        def __init__(self,*args): self.active_job=None;self.queue=asyncio.Queue()
        async def start(self): pass
        async def close(self): pass
    cfg=Config(tmp_path/'api');app=create_app(cfg,manager_factory=Manager,access_token='test-only')
    with TestClient(app,base_url='http://127.0.0.1:8876') as client:
        assert client.get('/api/memories').status_code==401
        headers={'X-Clara-Request':'1'}
        assert client.post('/api/session',json={'token':'test-only'},headers=headers).status_code==200
        cid=client.post('/api/conversations',json={},headers=headers).json()['id']
        begin=client.post('/api/conversations/'+cid+'/workflow',json={'kind':'t1-print','context':{'client_key':'test','year':'2025','members':['Test Person']}},headers=headers)
        assert begin.status_code==200
        assert client.post('/api/conversations/'+cid+'/workflow/review',json={'note':'Looks done'},headers=headers).status_code==400
        pdf=tmp_path/'ref.pdf';make_pdf(pdf,'Test printing reference')
        details={'title':'Test manual','library':'K04','metadata':{'source':'Test PDF'}}
        response=client.post('/api/knowledge/import',files={'file':('ref.pdf',pdf.read_bytes(),'application/pdf')},data={'details':json.dumps(details)},headers=headers)
        assert response.status_code==200
        assert any(r['title']=='Test manual' for r in client.get('/api/knowledge').json()['records'])


def test_prequery_login_failure_does_not_poison_workflow_usage(env,monkeypatch):
    from clara.agent import AgentManager
    cfg,s,j,w=env;begin(w,j)
    async def auth(): return {'connected':False,'message':'Login required'}
    monkeypatch.setattr('clara.agent.auth_status',auth)
    with pytest.raises(ValueError,match='Login required'): asyncio.run(AgentManager(cfg,s).execute(j))
    usage=json.loads(s.job(j['id'])['usage'])
    assert usage['coverage']=='reported' and usage['total_tokens']==0 and usage['turns']==0
    assert not w.remaining(j['conversation_id'])['partial']
