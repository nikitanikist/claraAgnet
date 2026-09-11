"""Bounded, source-linked retrieval and reviewed procedural memory."""
import hashlib
import json
import re
import time
from .store import new_id

LIBRARIES = {'K01':'Personal tax', 'K02':'Corporate tax', 'K03':'GST/HST and payroll',
             'K04':'Tax applications', 'K05':'Accounting applications', 'K06':'Document platforms',
             'K07':'Firm procedures', 'K08':'Verified examples'}


def decode(row, *columns):
    if row:
        row = dict(row)
        for c in columns:
            row[c] = json.loads(row[c])
    return row


def job_scope(store, job):
    workflow = store.one('SELECT w.context FROM workflows w JOIN workflow_jobs j ON w.id=j.workflow_id WHERE j.job_id=?', (job['id'],))
    if workflow:
        context = json.loads(workflow['context'])
        if context.get('client_key'):
            return 'client:' + context['client_key']
    return 'conversation:' + job['conversation_id']


class Knowledge:
    def __init__(self, store):
        self.store = store

    def add(self, title, text, library, metadata, scope_key='firm'):
        if library not in LIBRARIES or not title.strip() or len(title) > 180:
            raise ValueError('Choose a knowledge library and a title of 1–180 characters.')
        if not text.strip() or len(text) > 500_000:
            raise ValueError('Provide 1–500,000 characters of knowledge text.')
        if not metadata.get('source'):
            raise ValueError('A source URL or document name is required.')
        allowed = {'source','publisher','section','application','build','tax_year','jurisdiction','retrieved_at','notes'}
        metadata = {k:str(v)[:2000] for k,v in metadata.items() if k in allowed}
        metadata.setdefault('retrieved_at',time.strftime('%Y-%m-%d'))
        digest = hashlib.sha256((text+json.dumps(metadata,sort_keys=True)).encode()).hexdigest()
        existing = self.store.one('SELECT id FROM knowledge WHERE scope_key=? AND library=? AND content_hash=?', (scope_key,library,digest))
        if existing:
            return {'id':existing['id'],'duplicate':True}
        kid = new_id()
        chunks = []
        for paragraph in re.split(r'\n\s*\n',title+'\n\n'+text):
            for pos in range(0,len(paragraph),3000):
                piece = paragraph[pos:pos+3000]
                if piece.strip():
                    if chunks and len(chunks[-1])+len(piece)<3000:
                        chunks[-1]+='\n\n'+piece
                    else:
                        chunks.append(piece)
        with self.store.connect() as db:
            db.execute('INSERT INTO knowledge VALUES(?,?,?,?,?,?,?,?)', (kid,scope_key,library,title,json.dumps(metadata),digest,'active',time.time()))
            db.executemany('INSERT INTO knowledge_chunks(knowledge_id,ordinal,text) VALUES(?,?,?)',
                           [(kid,i,piece) for i,piece in enumerate(chunks,1)])
        return {'id':kid,'chunks':len(chunks)}

    def list(self, scope_key='firm'):
        return [decode(r,'metadata') for r in self.store.rows('SELECT * FROM knowledge WHERE scope_key IN (?,\'firm\') ORDER BY created DESC', (scope_key,))]

    def search(self, query, scope_key='firm', library=None, application=None, build=None, tax_year=None, limit=6):
        words = re.findall(r'[^\W_]+',query, re.UNICODE)[:18]
        if not words:
            return []
        expression = ' OR '.join('"'+w+'"' for w in words)
        clauses = ["knowledge_search MATCH ?", "k.status='active'", "k.scope_key IN (?, 'firm')"]
        args = [expression,scope_key]
        if library:
            clauses.append('k.library=?');args.append(library)
        for key,value in [('application',application),('build',build),('tax_year',tax_year)]:
            if value:
                clauses.append(f"(json_extract(k.metadata,'$.{key}') IS NULL OR json_extract(k.metadata,'$.{key}') IN ('',?))")
                args.append(str(value))
        rows = self.store.rows("SELECT k.id,k.title,k.library,k.metadata,c.ordinal,c.text,bm25(knowledge_search) rank "
            "FROM knowledge_search JOIN knowledge_chunks c ON c.id=knowledge_search.rowid JOIN knowledge k ON k.id=c.knowledge_id WHERE "
            +' AND '.join(clauses)+' ORDER BY rank LIMIT ?',(*args,min(10,max(1,limit))))
        return [{**decode(r,'metadata'),'citation':f"knowledge:{r['id']}#{r['ordinal']}"} for r in rows]

    def retire(self, kid):
        if not self.store.execute("UPDATE knowledge SET status='retired' WHERE id=?",(kid,)):
            raise ValueError('Knowledge record not found.')


class Memory:
    def __init__(self, store):
        self.store=store

    def propose(self, job, title, application, build, payload, kind='procedure'):
        if kind not in {'procedure','client_fact','firm_preference'}:
            raise ValueError('Unknown memory kind.')
        if not title.strip() or len(title)>180 or len(json.dumps(payload))>18000:
            raise ValueError('Keep a memory title below 180 characters and details below 18 KB.')
        if kind=='procedure' and (not application or not build or not all(payload.get(k) for k in ['preconditions','actions','postconditions'])):
            raise ValueError('A procedure needs application/build, preconditions, actions and verifiable postconditions.')
        mid=new_id(); now=time.time()
        self.store.execute('INSERT INTO memories VALUES(?,?,?,?,?,?,?,?,?,0,?,?)',
            (mid,job['id'],job_scope(self.store,job),kind,title,application,build,json.dumps(payload),'candidate',now,now))
        self.audit(mid,'proposed','Candidate saved from a task; not yet qualified.')
        return self.get(mid)

    def get(self, mid):
        return decode(self.store.one('SELECT * FROM memories WHERE id=?',(mid,)),'payload')

    def list(self, scope_key=None):
        rows=self.store.rows('SELECT * FROM memories ORDER BY updated DESC') if scope_key is None else self.store.rows(
            "SELECT * FROM memories WHERE scope_key IN (?, 'firm') ORDER BY updated DESC",(scope_key,))
        return [decode(r,'payload') for r in rows]

    def retrieve(self, job, query='', application='', build=''):
        items=self.list(job_scope(self.store,job));words=set(re.findall(r'\w+',query.lower()))
        matches=[]
        for m in items:
            if m['status'] not in {'qualified','provisional','candidate'}:
                continue
            if application and m['application'].casefold()!=application.casefold():
                continue
            if m['kind']=='procedure' and (not build or m['build']!=build):
                continue
            expired=time.time()-m['updated']>90*86400
            score=len(words & set(re.findall(r'\w+', (m['title']+' '+json.dumps(m['payload'])).lower())))
            if query and not score:
                continue
            matches.append({**m,'relevance':score,'expired':expired,'reuse_allowed':bool(m['status']=='qualified' and m['reviewed'] and not expired)})
        return sorted(matches,key=lambda x:(x['reuse_allowed'],x['relevance']),reverse=True)[:5]

    def begin_use(self, job, mid, build):
        m=self.get(mid)
        if not m or m['scope_key'] not in {'firm',job_scope(self.store,job)}:
            raise ValueError('Memory is outside this task scope.')
        if m['status'] in {'suspended','retired'} or m['build']!=build:
            raise ValueError('Procedure is suspended or does not match the current application build.')
        self.store.execute('INSERT OR IGNORE INTO memory_uses VALUES(?,?,?,?)',(new_id(),mid,job['id'],time.time()))
        return {'memory':m,'instruction':'Inspect live preconditions before using this procedure. Provisional methods still require validation.'}

    def validate(self, job, mid, evidence_id):
        use=self.store.one('SELECT * FROM memory_uses WHERE memory_id=? AND job_id=?',(mid,job['id']))
        evidence=decode(self.store.one('SELECT * FROM evidence WHERE id=? AND job_id=?',(evidence_id,job['id'])),'payload')
        if not use or not evidence or not evidence['verified'] or evidence['created']<use['started']:
            raise ValueError('Validation needs runtime-verified evidence created during a recorded use in this task.')
        if evidence['kind'] not in {'document','desktop_assertion','remote_record'}:
            raise ValueError('This evidence does not validate a procedure outcome.')
        m=self.get(mid)
        if not m or m['status'] in {'suspended','retired'}:
            raise ValueError('This memory cannot be validated.')
        # File hashes or remote/application identities are captured by validators, not supplied as a success flag.
        case_key=evidence['payload'].get('case_key') or evidence['payload'].get('sha256')
        if not case_key:
            raise ValueError('The evidence has no independently recorded case identity.')
        self.store.execute('INSERT OR IGNORE INTO memory_validations VALUES(?,?,?,?,?,?,?)',
            (new_id(),mid,job['id'],evidence_id,case_key,1,time.time()))
        self.refresh(mid);return self.get(mid)

    def refresh(self,mid):
        m=self.get(mid)
        if m['status'] in {'suspended','retired'}:
            return
        counts=self.store.one('SELECT COUNT(*) n,COUNT(DISTINCT v.case_key) cases,COUNT(DISTINCT j.conversation_id) conversations '
            'FROM memory_validations v JOIN jobs j ON j.id=v.job_id WHERE v.memory_id=? AND v.success=1 AND v.created>?',(mid,time.time()-90*86400))
        qualified = m['reviewed'] and (m['kind']!='procedure' or counts['n']>=3 and counts['cases']>=2 and counts['conversations']>=2)
        status='qualified' if qualified else 'provisional' if counts['n'] else 'candidate'
        self.store.execute('UPDATE memories SET status=?,updated=? WHERE id=?',(status,time.time(),mid))

    def review(self,mid,action,note='',share=False):
        m=self.get(mid)
        if not m:
            raise ValueError('Memory not found.')
        if action=='approve':
            if m['status'] in {'suspended','retired'}:
                raise ValueError('Create a corrected candidate instead of approving a suspended/retired procedure.')
            if share and m['kind']=='client_fact':
                raise ValueError('Client facts cannot be promoted to firm memory.')
            self.store.execute('UPDATE memories SET reviewed=1,scope_key=?,updated=? WHERE id=?',
                ('firm' if share else m['scope_key'],time.time(),mid));self.refresh(mid)
        elif action in {'suspend','retire'}:
            self.store.execute('UPDATE memories SET status=?,updated=? WHERE id=?',('suspended' if action=='suspend' else 'retired',time.time(),mid))
        else:
            raise ValueError('Choose approve, suspend or retire.')
        self.audit(mid,action,note);return self.get(mid)

    def audit(self,mid,action,note):
        self.store.execute('INSERT INTO memory_audit(memory_id,action,note,created) VALUES(?,?,?,?)',(mid,action,note[:2000],time.time()))
