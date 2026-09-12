"""Evidence-backed workflow state; a successful model reply cannot certify a closeout."""
import hashlib
import json
import re
import time
from pathlib import Path
from .store import new_id
from .knowledge import decode

TEMPLATES = {
 't1-closeout': ['intake','source-copy','application','documents','signature-packet','invoice','delivery','review'],
 't1-print': ['intake','source-copy','application','documents','review'],
 't1-preparation': ['intake','evidence','entries','diagnostics','review'],
 't2-preparation': ['intake','trial-balance','adjustments','gifi','return','diagnostics','review'],
 'bookkeeping': ['intake','evidence','transactions','reconciliation','review'],
 'bank-reconciliation': ['intake','statements','ledger','reconciliation','review'],
 'year-end': ['intake','trial-balance','adjustments','working-papers','review'],
 'gst-hst': ['intake','evidence','reconciliation','return','review'],
 'payroll': ['intake','inputs','calculations','reconciliation','review'],
 'information-slips': ['intake','evidence','slips','reconciliation','review'],
 'invoicing': ['intake','draft','review'],
 'correspondence': ['intake','evidence','draft','review'],
 'filing': ['intake','authorization','transmission','confirmation','review'],
 'general': ['work','review'],
}


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


class Workflows:
    def __init__(self,store,config): self.store,self.config=store,config

    def get(self,cid):
        return decode(self.store.one('SELECT * FROM workflows WHERE conversation_id=?',(cid,)),'context','contract','limits')

    def attach(self,job):
        w=self.get(job['conversation_id'])
        if w and job.get('id'):
            self.store.execute('INSERT OR IGNORE INTO workflow_jobs VALUES(?,?)',(job['id'],w['id']))
        return w

    def begin(self,job,kind,context,requirements=None):
        if kind not in TEMPLATES:
            raise ValueError('Choose a supported workflow type: '+', '.join(TEMPLATES))
        existing=self.get(job['conversation_id'])
        if existing:
            self.attach(job)
            if existing['kind']!=kind:
                raise ValueError('This conversation already has a different workflow. Start a new conversation.')
            if any(context.get(k) is not None and str(context[k])!=str(existing['context'].get(k)) for k in ['client_key','year','members','document_types']):
                raise ValueError('This workflow belongs to another client, year or output scope. Start a new conversation.')
            return self.snapshot(job['conversation_id'])
        if len(json.dumps(context))>16000:
            raise ValueError('Workflow context exceeds 16 KB.')
        if kind!='general' and (not context.get('client_key') or not context.get('year')):
            raise ValueError('Provide a client/engagement key and year before beginning this workflow.')
        if context.get('client_key') and not isinstance(context['client_key'],str):
            raise ValueError('Client key must be text.')
        contract = {stage:[] for stage in TEMPLATES[kind]}
        for stage,specs in (requirements or {}).items():
            if stage not in contract or not isinstance(specs,list) or len(specs)>40:
                raise ValueError('Invalid stage requirement list.')
            contract[stage]=specs
        if kind in {'t1-closeout','t1-print'}:
            members=context.get('members',[])
            if not isinstance(members,list) or not 1<=len(members)<=10 or any(not isinstance(m,str) or not m.strip() for m in members):
                raise ValueError('List the exact client names required for this T1 closeout.')
            # Required documents cannot be removed by a model-provided stage list.
            types=['client-copy','t183','engagement-letter'] if kind=='t1-closeout' else context.get('document_types',['client-copy'])
            if not isinstance(types,list) or not types or any(t not in {'client-copy','t183','engagement-letter'} for t in types):
                raise ValueError('Choose client-copy, t183 and/or engagement-letter document types.')
            contract['documents']=[{'kind':'document','member':m,'document_type':d,'year':str(context['year'])}
                for m in members for d in types]
            contract['source-copy']=[{'kind':'source-copy'}]
            contract['application']=[{'kind':'desktop_assertion'}]
            if kind=='t1-closeout':
                contract['signature-packet']=[{'kind':'remote_record','system':'pandadoc'}]
                contract['invoice']=[{'kind':'remote_record','system':'billing'}]
                contract['delivery']=[{'kind':'remote_record','system':'storage'},{'kind':'remote_record','system':'portal'}]
        now=time.time();settings=self.config.settings();wid=new_id()
        limits={k:settings.get(k) for k in ['max_turns','task_timeout_minutes','max_budget_usd']}
        self.store.execute('INSERT INTO workflows VALUES(?,?,?,?,?,?,?,?,?)',
            (wid,job['conversation_id'],kind,json.dumps(context),json.dumps(contract),json.dumps(limits),'active',now,now))
        self.attach(job)
        self.event(job,'workflow',{'id':wid,'kind':kind,'stages':TEMPLATES[kind]})
        return self.snapshot(job['conversation_id'])

    def evidence(self,job,kind,subject,payload,verified):
        eid=new_id()
        self.store.execute('INSERT INTO evidence VALUES(?,?,?,?,?,?,?)',(eid,job['id'],kind,subject,json.dumps(payload),int(verified),time.time()))
        self.event(job,'evidence',{'id':eid,'kind':kind,'subject':subject,'verified':bool(verified),'checks':payload.get('checks',[])})
        return {'id':eid,'kind':kind,'verified':bool(verified),**payload}

    def event(self,job,kind,data): self.store.event(job['conversation_id'],job['id'],kind,data)

    def verify_document(self,job,path,member,document_type,year,required_text=None,min_pages=1):
        from .tools import permitted_path
        from pypdf import PdfReader
        source=permitted_path(self.config,path)
        if source.suffix.lower()!='.pdf' or not source.is_file() or source.stat().st_size>50_000_000:
            raise ValueError('Choose a PDF of 50 MB or less for document verification.')
        w=self.get(job['conversation_id']);context=w['context'] if w else {}
        if context.get('members') and member not in context['members']:
            raise ValueError('This member is not part of the workflow.')
        if context.get('year') and str(year)!=str(context['year']):
            raise ValueError('Document year does not match the workflow.')
        if not member or not year or document_type not in {'client-copy','t183','engagement-letter','invoice','working-paper','report'}:
            raise ValueError('Provide member, year and a supported document type.')
        data=source.read_bytes();digest=hashlib.sha256(data).hexdigest()
        import io
        reader=PdfReader(io.BytesIO(data))
        if reader.is_encrypted or len(reader.pages)>1000:
            raise ValueError('Use a readable PDF of at most 1,000 pages.')
        page_text=[p.extract_text() or '' for p in reader.pages]
        normalized=lambda text: re.sub(r'\s+',' ',text).casefold()
        text=normalized('\n'.join(page_text))
        # These checks are measurable, but not a substitute for visual/accounting review.
        checks=[{'name':'readable_text','passed':bool(text.strip())},
                {'name':'minimum_pages','passed':len(reader.pages)>=max(1,min_pages)},
                {'name':'member','passed':normalized(member) in text}]
        if document_type!='engagement-letter':
            checks.append({'name':'tax_year','passed':str(year) in text})
        type_tokens={'t183':['t183'],'engagement-letter':['engagement'],'client-copy':['income','tax']}
        for needle in type_tokens.get(document_type,[])+(required_text or []):
            checks.append({'name':'contains:'+needle,'passed':normalized(needle) in text})
        ok=all(c['passed'] for c in checks)
        payload={'path':str(source),'sha256':digest,'pages':len(reader.pages),'member':member,'year':str(year),
                 'document_type':document_type,'checks':checks,'case_key':context.get('client_key',job['conversation_id'])+':'+str(year),
                 'coverage':'Text/identity/content checks only. Visual completeness and tax correctness require review.'}
        return self.evidence(job,'document',source.name,payload,ok)

    def _proofs(self,job,evidence_ids):
        if not isinstance(evidence_ids,list) or len(evidence_ids)>100 or any(not isinstance(e,str) for e in evidence_ids):
            raise ValueError('Provide at most 100 evidence ID strings.')
        proofs=[]
        for eid in dict.fromkeys(evidence_ids):
            row=decode(self.store.one('SELECT e.* FROM evidence e JOIN jobs j ON j.id=e.job_id WHERE e.id=? AND j.conversation_id=?',
                                     (eid,job['conversation_id'])),'payload')
            if not row or not row['verified']:
                raise ValueError('Evidence is missing, unverified or belongs to another conversation.')
            if row['kind'] in {'document','source-copy'}:
                from .tools import permitted_path
                payload=row['payload'];path=permitted_path(self.config,payload['path'])
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=payload['sha256']:
                    raise ValueError('An evidenced file changed or disappeared. Re-verify it before advancing.')
            proofs.append(row)
        return proofs

    def checkpoint(self,job,stage,evidence_ids,note='',status='verified'):
        w=self.get(job['conversation_id'])
        if not w:
            raise ValueError('Start a workflow before saving a stage checkpoint.')
        if stage not in w['contract'] or status not in {'verified','needs_review','blocked'}:
            raise ValueError('Choose a configured stage and verified, needs_review or blocked status.')
        snapshot=self.snapshot(job['conversation_id']); stages=list(w['contract']);idx=stages.index(stage)
        if status=='verified':
            previous=[s for s in stages[:idx] if snapshot['stages'][s]['status']!='verified']
            if previous:
                raise ValueError('Complete earlier stages first: '+', '.join(previous))
        proofs=self._proofs(job,evidence_ids)
        if status=='verified' and stage not in {'intake'} and not proofs:
            raise ValueError('A verified stage needs runtime evidence. Save blocked/needs_review for an explanation alone.')
        if status=='verified':
            for requirement in w['contract'][stage]:
                matched=any(all((p['kind'] if key=='kind' else p['payload'].get(key))==value for key,value in requirement.items()) for p in proofs)
                if not matched:
                    raise ValueError('Required evidence is missing: '+json.dumps(requirement))
        if stage=='review' and status=='verified':
            raise ValueError('Final review is recorded by the operator in the dashboard. Save needs_review with the evidence package.')
        cid=new_id();now=time.time()
        self.store.execute('INSERT INTO checkpoints VALUES(?,?,?,?,?,?,?,?)',(cid,w['id'],job['id'],stage,status,json.dumps(evidence_ids),note[:6000],now))
        self.store.execute('UPDATE workflows SET updated=?,status=? WHERE id=?',(now,'needs_review' if stage=='review' else 'active',w['id']))
        self.event(job,'checkpoint',{'stage':stage,'status':status,'evidence_ids':evidence_ids,'note':note[:6000]})
        return self.snapshot(job['conversation_id'])

    def snapshot(self,cid):
        w=self.get(cid)
        if not w:
            return None
        stages={s:{'status':'pending','evidence_ids':[],'note':''} for s in w['contract']}
        for row in self.store.rows('SELECT * FROM checkpoints WHERE workflow_id=? ORDER BY created',(w['id'],)):
            stages[row['stage']]={**row,'evidence_ids':json.loads(row['evidence_ids'])}
        if w['status']=='completed':
            stages['review']['status']='approved'
        return {**w,'stages':stages,'budget':self.remaining(cid)}

    def remaining(self,cid):
        w=self.get(cid)
        if not w:
            return None
        rows=self.store.rows('SELECT j.id,j.usage,j.status FROM jobs j JOIN workflow_jobs l ON l.job_id=j.id WHERE l.workflow_id=?',(w['id'],))
        reviewed=self.store.one("SELECT data FROM events WHERE conversation_id=? AND kind='workflow_usage_review' ORDER BY id DESC LIMIT 1",(cid,))
        reviewed=json.loads(reviewed['data']).get('job_fingerprints',{}) if reviewed else {}
        used={'turns':0,'usd':0.0,'wall_ms':0};partial_jobs=[]
        for row in rows:
            usage=json.loads(row['usage']) if row['usage'] is not None else {}
            if not usage and row['status'] in {'queued','running','waiting','cancelling'}:
                continue
            used['turns']+=usage.get('turns') or 0
            used['usd']+=usage.get('sdk_estimated_usd') or 0
            used['wall_ms']+=usage.get('wall_duration_ms') or usage.get('duration_ms') or 0
            partial=usage.get('coverage')!='reported' or usage.get('turns') is None or (w['limits'].get('max_budget_usd') is not None and usage.get('sdk_estimated_usd') is None)
            if partial:
                fingerprint=canonical_hash({'job_id':row['id'],'status':row['status'],'usage':usage})
                partial_jobs.append({'job_id':row['id'],'status':row['status'],'fingerprint':fingerprint,
                    'reviewed':reviewed.get(row['id'])==fingerprint,'turns':usage.get('turns'),
                    'sdk_estimated_usd':usage.get('sdk_estimated_usd'),
                    'wall_duration_ms':usage.get('wall_duration_ms',usage.get('duration_ms'))})
        pending=[row for row in partial_jobs if not row['reviewed']]
        limits=w['limits']
        return {'used':used,'partial':bool(partial_jobs),'requires_usage_review':bool(pending),
                'partial_usage':partial_jobs,'unreviewed_usage':pending,
                'remaining_turns':None if limits['max_turns'] is None else max(0,limits['max_turns']-used['turns']),
                'remaining_usd':None if limits.get('max_budget_usd') is None else max(0,limits['max_budget_usd']-used['usd']),
                'remaining_ms':max(0,limits['task_timeout_minutes']*60000-used['wall_ms'])}

    def review_usage(self,cid,job_fingerprints,note):
        budget=self.remaining(cid)
        if budget is None: raise ValueError('No workflow exists in this conversation.')
        if not note.strip(): raise ValueError('Record why you are continuing with incomplete usage.')
        expected={row['job_id']:row['fingerprint'] for row in budget['unreviewed_usage']}
        if not expected or job_fingerprints!=expected:
            raise ValueError('The incomplete-usage history changed. Refresh Workflow review before continuing.')
        # Review permits continuation; it does not edit usage, checkpoints, limits,
        # session identity, or the uncertainty of an external application action.
        self.store.event(cid,None,'workflow_usage_review',{
            'job_fingerprints':{row['job_id']:row['fingerprint'] for row in budget['partial_usage']},
            'note':note[:4000],
            'coverage':'Missing usage remains unknown. Aggregate turn/cost totals are lower bounds; continuation uses the configured limits against reported usage.'})
        return self.snapshot(cid)

    def finish_check(self,job):
        state=self.snapshot(job['conversation_id'])
        if not state:
            return None
        for stage,record in state['stages'].items():
            if record['status'] in {'verified','approved'}:
                try: self._proofs(job,record['evidence_ids'])
                except ValueError as error:
                    self.store.execute("UPDATE workflows SET status='active' WHERE id=?",(state['id'],))
                    return 'Workflow incomplete. Evidence for '+stage+' no longer matches: '+str(error)
        required=[s for s in state['stages'] if s!='review']
        pending=[s for s in required if state['stages'][s]['status']!='verified']
        if pending:
            return 'Workflow incomplete. Remaining stages: '+', '.join(pending)+'. Progress has been saved.'
        if state['status']!='completed':
            return 'Work is ready for review. The workflow is not approved or filed merely because the model finished.'
        return None

    def review(self,cid,note):
        w=self.snapshot(cid)
        if not w:
            raise ValueError('Workflow not found.')
        if any(v['status']!='verified' for s,v in w['stages'].items() if s!='review'):
            raise ValueError('Complete the required stages before approving the package.')
        if not note.strip():
            raise ValueError('Record a short review note.')
        for stage in w['stages'].values():
            ids=stage['evidence_ids']
            if ids:
                jid=stage.get('job_id');self._proofs(self.store.job(jid),ids)
        self.store.execute("UPDATE workflows SET status='completed',updated=? WHERE id=?",(time.time(),w['id']))
        self.store.event(cid,None,'workflow_review',{'status':'completed','note':note[:4000]})
        return self.snapshot(cid)
