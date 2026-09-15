"""Workflow, retrieval, recovery and verifiable file capabilities shared across skills."""
import asyncio
import hashlib
import json
import shutil
from pathlib import Path
from .knowledge import Knowledge,Memory,job_scope,decode
from .workflows import Workflows
from .operations import Operations
from .evidence_index import evidence_index,evidence_detail


def schema(properties,required=()):
    kinds={'s':'string','i':'integer','b':'boolean','o':'object','a':'array'}
    return {'type':'object','properties':{k:({'type':kinds[v],**({'items':{}} if v=='a' else {})} if isinstance(v,str) else v) for k,v in properties.items()},'required':list(required)}


def definitions(config,store,job):
    from .tools import permitted_path,publish_artifact
    wf=Workflows(store,config);knowledge=Knowledge(store);memory=Memory(store);ops=Operations(store)
    def sync(fn):
        async def run(args): return await asyncio.to_thread(fn,args)
        return run
    def file_info(args):
        p=permitted_path(config,args['path'])
        if not p.is_file(): raise ValueError('Choose a file.')
        digest=hashlib.sha256()
        with p.open('rb') as f:
            for block in iter(lambda:f.read(1_048_576),b''): digest.update(block)
        return {'path':str(p),'bytes':p.stat().st_size,'modified':p.stat().st_mtime,'sha256':digest.hexdigest()}
    def copy(args):
        source=permitted_path(config,args['source']);target=permitted_path(config,args['destination'],write=True)
        if not source.is_file() or source.stat().st_size>500_000_000: raise ValueError('Source must be a file under 500 MB.')
        target.parent.mkdir(parents=True,exist_ok=True)
        # Exclusive create: never overwrite a previous run's copy.
        with source.open('rb') as src,target.open('xb') as dst: shutil.copyfileobj(src,dst)
        original=file_info({'path':str(source)});copied=file_info({'path':str(target)})
        return wf.evidence(job,'source-copy',target.name,{**copied,'source':str(source),'source_sha256':original['sha256']},copied['sha256']==original['sha256'])
    def resume(args):
        state=wf.snapshot(job['conversation_id'])
        proofs=[]
        if state:
            for name,stage in state['stages'].items():
                try: wf._proofs(job,stage['evidence_ids']);valid=True
                except ValueError: valid=False
                proofs.append({'stage':name,'saved_status':stage['status'],'files_still_match':valid})
        return {'workflow':state,'checks':proofs,'operations':ops.list(job),
                'last_execution':store.one('SELECT s.* FROM execution_snapshots s JOIN jobs j ON j.id=s.job_id WHERE j.conversation_id=? ORDER BY s.updated DESC LIMIT 1',(job['conversation_id'],)),
                'instruction':'Inspect current application/remote state before resuming. Saved observations can be stale. Never replay uncertain external writes.'}
    def remote(args):
        proof=decode(store.one('SELECT * FROM evidence WHERE id=? AND job_id=?',(args['observation_id'],job['id'])),'payload')
        if not proof or proof['kind']!='tool_observation' or not proof['payload'].get('tool','').startswith('mcp__chrome__') or proof['payload'].get('error'):
            raise ValueError('Use a fresh Chrome observation from this task, after opening the actual record.')
        import time
        if time.time()-proof['created']>300: raise ValueError('Remote observation is older than five minutes. Read it again.')
        text=proof['payload']['text']
        values={k:str(args[k]) for k in ['url','remote_id','external_key','client_name','status']}
        if not values['url'].startswith('https://') or any(not v.strip() or v.casefold() not in text.casefold() for v in values.values()):
            raise ValueError('Record URL, ID, business key, client and status must all appear in the observed page text. Take another snapshot or use an operator review for unsupported UIs.')
        w=wf.get(job['conversation_id']);context=w['context'] if w else {}
        if context.get('members') and args['client_name'] not in context['members']:
            raise ValueError('Remote client does not match this workflow.')
        return wf.evidence(job,'remote_record',values['remote_id'],{**values,'system':args['system'],
            'observation_id':proof['id'],'case_key':context.get('client_key',job['conversation_id']),
            'coverage':'Observed browser text matched these fields. Operator reviews recipient placement, monetary values and final submission.'},True)
    def handoff(args):
        state=wf.snapshot(job['conversation_id'])
        evidence=[decode(r,'payload') for r in store.rows('SELECT e.* FROM evidence e JOIN jobs j ON j.id=e.job_id WHERE j.conversation_id=? AND e.kind!=? ORDER BY e.created',(job['conversation_id'],'tool_observation'))]
        path=config.workspace/'outputs'/job['id']/'clara-handoff.json';path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps({'workflow':state,'evidence':evidence,'operations':ops.list(job),'note':args.get('note',''),'completion':wf.finish_check(job)},indent=2),encoding='utf-8')
        return publish_artifact(config,store,job,str(path),'Workflow handoff and verification')
    def memory_action(a):
        action=a['action']
        if action=='begin_use': return memory.begin_use(job,a['id'],a['build'])
        if action=='validate': return memory.validate(job,a['id'],a['evidence_id'])
        if action=='invalidate':
            m=memory.get(a['id'])
            if not m or m['scope_key'] not in {'firm',job_scope(store,job)}: raise ValueError('Memory outside this scope.')
            return memory.review(a['id'],'suspend',a.get('reason','Failed live verification'))
        raise ValueError('Choose begin_use, validate or invalidate. Operator approval is in the dashboard.')
    attempt=store.one('SELECT claim_json FROM portal_v1_attempts WHERE local_job_id=?',(job['id'],))
    portal_claim=json.loads(attempt['claim_json']) if attempt else None
    portal_claim=portal_claim if portal_claim and portal_claim.get('kind')=='closeout' else None
    def reserve(a):
        if portal_claim:
            from .portal_outputs import closeout_reservation_keys
            keys=closeout_reservation_keys(portal_claim)
            allowed=sorted(keys.get(a.get('system'),{}).values())
            if a.get('key') not in allowed:
                raise ValueError('A portal closeout reserves only its canonical keys. '+
                    ('Allowed for %s: %s.'%(a.get('system'),', '.join(allowed)) if allowed else
                     'Allowed systems: '+'; '.join('%s: %s'%(s,', '.join(sorted(v.values()))) for s,v in keys.items())+'.'))
        return ops.reserve(job,**a)
    items=[
      ('stat_file','Get file size, modification time and SHA-256 without opening Explorer.',schema({'path':'s'},['path']),file_info),
      ('copy_file','Create an exclusive working copy and verify source/copy hashes.',schema({'source':'s','destination':'s'},['source','destination']),copy),
      ('begin_workflow','Start the appropriate business workflow before actions; context needs client_key/year and T1 members. Scope is fixed per conversation.',schema({'kind':'s','context':'o','requirements':'o'},['kind','context']),lambda a:wf.begin(job,a['kind'],a['context'],a.get('requirements'))),
      ('read_task','Read current workflow stages and aggregate budget.',schema({}),lambda a:wf.snapshot(job['conversation_id'])),
      ('save_checkpoint','Save a stage with evidence IDs, or mark blocked/needs_review. Cannot claim final approval.',schema({'stage':'s','evidence_ids':'a','note':'s','status':'s'},['stage','evidence_ids']),lambda a:wf.checkpoint(job,a['stage'],a['evidence_ids'],a.get('note',''),a.get('status','verified'))),
      ('prepare_resume','Recheck output hashes and load previous progress/uncertain actions. Observe live UI before continuing.',schema({}),resume),
      ('verify_output','Verify PDF text, identity, year, type and page count. This does not certify tax correctness or visual completeness.',schema({'path':'s','member':'s','document_type':'s','year':'s','required_text':'a','min_pages':'i'},['path','member','document_type','year']),lambda a:wf.verify_document(job,**a)),
      ('list_evidence','Compact, paginated evidence index. Business evidence by default; select kind=tool_observation or an exact tool name for raw observation IDs. Use get_evidence for details.',schema({'kind':'s','tool':'s','limit':'i','before':'s'}),lambda a:evidence_index(store,job['conversation_id'],**a)),
      ('get_evidence','Read one evidence record in bounded text chunks. Use next_offset only when more detail is necessary. No direct database access is needed.',schema({'id':'s','offset':'i','length':'i'},['id']),lambda a:evidence_detail(store,job['conversation_id'],**a)),
      ('retrieve_knowledge','Search source-linked knowledge for this client/firm; use software build and tax year filters.',schema({'query':'s','library':'s','application':'s','build':'s','tax_year':'s'},['query']),lambda a:knowledge.search(scope_key=job_scope(store,job),**a)),
      ('retrieve_memory','Retrieve scoped lessons for the exact application build. Candidates are not qualified procedures.',schema({'query':'s','application':'s','build':'s'}),lambda a:memory.retrieve(job,**a)),
      ('propose_memory','Save a candidate lesson with preconditions/actions/postconditions. No model self-approval.',schema({'title':'s','application':'s','build':'s','payload':'o','kind':{'type':'string','enum':['procedure','client_fact']}},['title','application','build','payload']),lambda a:memory.propose(job,**a)),
      ('memory_use','Record procedure use before actions, validate after runtime evidence, or invalidate after failure.',schema({'action':'s','id':'s','build':'s','evidence_id':'s','reason':'s'},['action','id']),memory_action),
      ('reserve_external_write','Reserve one external-write attempt by stable client/business key before creating invoices, signature packets or uploads. Existing keys cannot be replayed.',schema({'system':'s','operation':'s','key':'s','request':'o'},['system','operation','key','request']),reserve),
      ('verify_remote_record','Match remote record fields against fresh Chrome readback, not an assistant claim.',schema({k:'s' for k in ['observation_id','system','url','remote_id','external_key','client_name','status']},['observation_id','system','url','remote_id','external_key','client_name','status']),remote),
      ('reconcile_external_write','Confirm a reserved operation using verified remote-record evidence.',schema({'id':'s','evidence_id':'s'},['id','evidence_id']),lambda a:ops.reconcile(job,a['id'],a['evidence_id'])),
      ('publish_handoff','Publish a local JSON evidence package, remaining stages, operations and budget for review.',schema({'note':'s'}),handoff),
    ]
    if attempt:
        from .portal_outputs import record_delivery
        def record_schema(fields):
            return schema({field: {'type': 'string', 'minLength': 1,
                                  'maxLength': 2000 if field == 'url' else 200}
                           for field in fields}, fields)
        items.append(('record_portal_delivery',
            'Record assigned T1 delivery using current Chrome observations. Supply document evidence IDs, '
            'one PandaDoc per member (member_id, remote_id, url, external_key, observation_id), '
            'folder (remote_id, url, external_key, observation_id), and files '
            '(member_id, document_type, tax_year, remote_file_id, observation_id). Observations must '
            'show recipient, business key, remote file name, exact byte size, file ID and folder ID. '
            'Returns checkpoint proofs; does not send email or approve the workflow.',
            schema({'document_evidence_ids': {'type':'array', 'items':{'type':'string'}, 'maxItems':100},
                    'pandadoc': {'type':'array', 'maxItems':100, 'items':record_schema(
                        ['member_id','remote_id','url','external_key','observation_id'])},
                    'folder': record_schema(['remote_id','url','external_key','observation_id']),
                    'files': {'type':'array', 'maxItems':300, 'items':record_schema(
                        ['member_id','document_type','tax_year','remote_file_id','observation_id'])}},
                   ['document_evidence_ids','pandadoc','folder','files']),
            lambda a:record_delivery(config,store,job,a)))
    return [(name,description,args,sync(fn)) for name,description,args,fn in items]
