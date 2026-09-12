import asyncio
import json

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, SystemMessage, TextBlock
from fastapi.testclient import TestClient

from clara.agent import AgentManager
from clara.app import create_app
from clara.config import Config
from clara.store import Store
from clara.workflows import Workflows


def incomplete(tmp_path):
    cfg=Config(tmp_path/'data');cfg.initialize()
    store=Store(cfg.data/'clara.sqlite3');wf=Workflows(store,cfg)
    cid=store.create_conversation()['id'];job=store.create_job(cid,'Original task','ask',[])
    wf.begin(job,'t1-print',{'client_key':'test','year':'2025','members':['Test Person']})
    wf.checkpoint(job,'intake',[],note='Original intake is saved.')
    store.execute('UPDATE jobs SET status=?,usage=? WHERE id=?',('cancelled',json.dumps({
        'coverage':'partial','turns':None,'sdk_estimated_usd':None,'wall_duration_ms':26100}),job['id']))
    return cfg,store,wf,cid,job


def fingerprints(wf,cid):
    return {row['job_id']:row['fingerprint'] for row in wf.remaining(cid)['unreviewed_usage']}


def test_usage_review_preserves_unknown_usage_limits_and_checkpoints(tmp_path):
    cfg,s,wf,cid,job=incomplete(tmp_path)
    before=s.job(job['id'])['usage'];limits=wf.get(cid)['limits']
    state=wf.review_usage(cid,fingerprints(wf,cid),'Continue existing work despite the missing usage report.')
    assert state['budget']['partial'] and not state['budget']['requires_usage_review']
    assert state['limits']==limits and state['stages']['intake']['status']=='verified'
    assert s.job(job['id'])['usage']==before
    assert json.loads(before)['sdk_estimated_usd'] is None
    restarted=Workflows(Store(s.path),Config(cfg.data))
    assert not restarted.remaining(cid)['requires_usage_review']
    assert restarted.remaining(cid)['used']['wall_ms']==26100


@pytest.mark.parametrize('change',['new_stop','changed_report'])
def test_review_does_not_cover_new_or_changed_incomplete_reports(tmp_path,change):
    cfg,s,wf,cid,job=incomplete(tmp_path)
    original=fingerprints(wf,cid)
    wf.review_usage(cid,original,'Continue with incomplete usage.')
    if change=='new_stop':
        new=s.create_job(cid,'Another interrupted request','autonomous',[]);wf.attach(new)
        s.status(new['id'],'interrupted')
    else:
        s.execute('UPDATE jobs SET usage=? WHERE id=?',(json.dumps({'coverage':'partial','turns':2,'wall_duration_ms':28000}),job['id']))
    assert wf.remaining(cid)['requires_usage_review']
    with pytest.raises(ValueError,match='history changed'): wf.review_usage(cid,original,'Stale review')


@pytest.mark.parametrize('spent',['time','cost'])
def test_review_does_not_remove_exhausted_known_budgets(tmp_path,monkeypatch,spent):
    cfg,s,wf,cid,job=incomplete(tmp_path)
    limits={**wf.get(cid)['limits'],'max_turns':None,'task_timeout_minutes':1,'max_budget_usd':1}
    s.execute('UPDATE workflows SET limits=? WHERE conversation_id=?',(json.dumps(limits),cid))
    prior=s.create_job(cid,'Known usage','ask',[]);wf.attach(prior)
    s.execute('UPDATE jobs SET status=?,usage=? WHERE id=?',('failed',json.dumps({
        'coverage':'reported','turns':2,'sdk_estimated_usd':1 if spent=='cost' else 0,
        'wall_duration_ms':60000 if spent=='time' else 1}),prior['id']))
    wf.review_usage(cid,fingerprints(wf,cid),'Continue with incomplete usage.')
    async def auth(): return {'connected':True,'plan':'test'}
    monkeypatch.setattr('clara.agent.auth_status',auth)
    new=s.create_job(cid,'Continue','autonomous',[])
    with pytest.raises(ValueError,match='budget exhausted'): asyncio.run(AgentManager(cfg,s).execute(new))


def test_operator_review_requires_session_idle_and_matching_history(tmp_path):
    cfg,s,wf,cid,job=incomplete(tmp_path)
    class Manager:
        def __init__(self,*args): self.active_job=None;self.queue=asyncio.Queue()
        async def start(self): pass
        async def close(self): pass
    app=create_app(cfg,manager_factory=Manager,access_token='test-only')
    route=f'/api/conversations/{cid}/workflow/review-usage'
    body={'job_fingerprints':fingerprints(wf,cid),'note':'Continue with saved work.'}
    with TestClient(app,base_url='http://127.0.0.1:8876') as client:
        client.headers['x-clara-request']='1'
        assert client.post(route,json=body).status_code==401
        client.post('/api/session',json={'token':'test-only'}).raise_for_status()
        app.state.manager.active_job='busy'
        assert client.post(route,json=body).status_code==400
        app.state.manager.active_job=None
        assert client.post(route,json={**body,'job_fingerprints':{'other-job':'wrong'}}).status_code==400
        assert client.post(route,json={**body,'note':''}).status_code==422
        assert client.post(route,json=body).status_code==200
        assert not client.get(f'/api/conversations/{cid}/workflow').json()['workflow']['budget']['requires_usage_review']


def test_autonomous_default_and_explicit_ask_preference(tmp_path):
    cfg=Config(tmp_path/'data');cfg.initialize()
    old=cfg.settings();old.pop('default_execution_mode');cfg.save_settings(old)
    assert Config(cfg.data).settings()['default_execution_mode']=='autonomous'
    class Manager:
        def __init__(self,config,store): self.store=store;self.active_job=None;self.queue=asyncio.Queue()
        async def start(self): pass
        async def close(self): pass
        def submit(self,cid,prompt,mode,attachments): return self.store.create_job(cid,prompt,mode,attachments)
    app=create_app(cfg,manager_factory=Manager,access_token='test-only')
    with TestClient(app,base_url='http://127.0.0.1:8876') as client:
        client.headers['x-clara-request']='1'
        client.post('/api/session',json={'token':'test-only'})
        cid=app.state.store.create_conversation()['id'];route=f'/api/conversations/{cid}/messages'
        assert client.post(route,json={'text':'Default task'}).json()['mode']=='autonomous'
        explicit=client.post(route,json={'text':'Ask task','mode':'ask'}).json()
        assert explicit['mode']=='ask'
        client.put('/api/settings',json={**cfg.settings(),'default_execution_mode':'ask'}).raise_for_status()
        assert Config(cfg.data).settings()['default_execution_mode']=='ask'
        assert client.post(route,json={'text':'Use saved preference'}).json()['mode']=='ask'
        assert client.post(route,json={'text':'Specific autonomy','mode':'autonomous'}).json()['mode']=='autonomous'
        assert app.state.store.job(explicit['id'])['mode']=='ask'


def test_cancel_during_permission_can_resume_after_usage_review(tmp_path,monkeypatch):
    waiting=asyncio.Event();options_seen=[];attempts=[]
    class SDK:
        def __init__(self,options): self.options=options;options_seen.append(options)
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def query(self,prompt): attempts.append(prompt)
        async def receive_response(self):
            if len(attempts)==1:
                yield SystemMessage(subtype='init',data={'session_id':'saved-session'})
                yield AssistantMessage(content=[TextBlock(text='Inspecting saved work')],model='test',message_id='first',usage={'input_tokens':20,'output_tokens':0})
                waiting.set()
                pre=self.options.hooks['PreToolUse'][0].hooks[0]
                await pre({'tool_name':'mcp__windows__Click','tool_input':{'loc':[10,10]}},'pending-click',{})
                raise AssertionError('A cancelled permission request must not dispatch the action')
            assert self.options.resume=='saved-session'
            assert 'Original intake is saved.' in attempts[-1]
            assert 'Previous tool observation' in attempts[-1] and 'pending-click' not in attempts[-1]
            yield ResultMessage(subtype='success',duration_ms=1,duration_api_ms=1,is_error=False,num_turns=1,
                session_id='saved-session',usage={'input_tokens':2,'output_tokens':2},total_cost_usd=0.01)
    async def auth(): return {'connected':True,'plan':'test'}
    monkeypatch.setattr('clara.agent.ClaudeSDKClient',SDK);monkeypatch.setattr('clara.agent.auth_status',auth)
    async def scenario():
        cfg=Config(tmp_path/'data');cfg.initialize();s=Store(cfg.data/'clara.sqlite3');wf=Workflows(s,cfg)
        cid=s.create_conversation()['id'];manager=AgentManager(cfg,s)
        wf.begin({'id':None,'conversation_id':cid},'t1-print',{'client_key':'test','year':'2025','members':['Test Person']})
        package=cfg.workspace/'existing-package';package.mkdir();output=package/'already-created.txt';output.write_text('Keep existing output')
        await manager.start()
        try:
            job=manager.submit(cid,'Original T1 test','ask',[])
            wf.checkpoint(job,'intake',[],note='Original intake is saved.')
            await asyncio.wait_for(waiting.wait(),3)
            assert manager.pending
            await manager.cancel(job['id'])
            await asyncio.wait_for(manager.queue.join(),3)
            assert s.job(job['id'])['status']=='cancelled'
            before=s.job(job['id'])['usage'];assert json.loads(before)['coverage']=='partial'
            retry=manager.submit(cid,'Continue','autonomous',[])
            await asyncio.wait_for(manager.queue.join(),3)
            assert s.job(retry['id'])['status']=='failed' and len(attempts)==1
            wf.review_usage(cid,fingerprints(wf,cid),'Stopped at permission prompt. Continue with saved work.')
            resumed=manager.submit(cid,'Continue','autonomous',[])
            await asyncio.wait_for(manager.queue.join(),3)
            assert len(attempts)==2
            assert s.job(resumed['id'])['status']=='incomplete'  # No test pretends to produce tax PDFs.
            assert s.job(job['id'])['usage']==before
            assert wf.remaining(cid)['partial'] and not wf.remaining(cid)['requires_usage_review']
            assert output.read_text()=='Keep existing output'
            assert wf.snapshot(cid)['stages']['intake']['status']=='verified'
        finally: await manager.close()
    asyncio.run(scenario())
