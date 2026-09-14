"""Optional outbound assignment worker for one explicitly configured operator.

The portal implements docs/PORTAL-PROTOCOL.md. No inbound desktop port is opened.
Disabled unless an operator installs portal.json with a URL, owner and token env.
"""
import asyncio
import json
import time
from urllib.parse import urlparse
import httpx
from .workflows import canonical_hash
from .auth import portal_credential

TERMINAL={'completed','needs_review','incomplete','failed','cancelled','interrupted'}


class PortalWorker:
    def __init__(self,config,store,manager):
        self.config,self.store,self.manager=config,store,manager
        self.task=None;self.error=None

    def settings(self):
        path=self.config.data/'portal.json'
        if not path.exists(): return None
        data=json.loads(path.read_text())
        if not data.get('enabled'): return None
        parsed=urlparse(data.get('base_url',''))
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Portal base_url must be HTTPS without credentials, query or fragment.')
        if not data.get('owner_key') or not data.get('worker_id') or not data.get('token_env','').startswith('CLARA_PORTAL_'):
            raise ValueError('Configure owner_key, worker_id and a CLARA_PORTAL_ token environment variable.')
        if not data.get('authentication_reviewed'):
            raise ValueError('Review the model account/authentication arrangement before enabling portal assignments.')
        return data

    def accept(self,assignment,settings):
        if not isinstance(assignment,dict) or not all(isinstance(assignment.get(k),str) and assignment[k].strip() for k in ['id','owner_key','prompt']):
            raise ValueError('Assignment needs id, owner_key and prompt.')
        if assignment['owner_key']!=settings['owner_key']:
            raise ValueError('Assignment belongs to another operator; this worker cannot share its model session.')
        if len(assignment['prompt'])>50000 or len(assignment['id'])>200:
            raise ValueError('Assignment is too large.')
        # Identity includes only immutable assignment fields, not transport lease timestamps.
        digest=canonical_hash({k:assignment.get(k) for k in ['id','owner_key','prompt','mode']})
        previous=self.store.one('SELECT * FROM portal_assignments WHERE external_id=?',(assignment['id'],))
        if previous:
            if previous['request_hash']!=digest: raise ValueError('Assignment ID was reused with different content.')
            return previous
        if self.manager.active_job or not self.manager.queue.empty(): return None
        mode='autonomous' if settings.get('allow_autonomous') and assignment.get('mode')=='autonomous' else 'ask'
        # Persist before enqueue. After a crash recovery marks the job interrupted rather than replaying it.
        with self.store.connect() as db:
            from .store import new_id
            cid=new_id();jid=new_id();now=time.time()
            db.execute('INSERT INTO conversations VALUES(?,?,?,NULL)',(cid,assignment['prompt'][:65],now))
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,NULL,NULL,?)',(jid,cid,assignment['prompt'],'queued',mode,now,'[]'))
            db.execute('INSERT INTO portal_assignments VALUES(?,?,?,?,?,?)',(assignment['id'],digest,cid,jid,assignment['owner_key'],now))
        self.store.event(cid,jid,'user',{'text':assignment['prompt'],'attachments':[]})
        self.store.event(cid,jid,'status',{'status':'queued'})
        self.manager.queue.put_nowait(jid)
        return self.store.one('SELECT * FROM portal_assignments WHERE external_id=?',(assignment['id'],))

    async def start(self):
        try:
            if self.settings(): self.task=asyncio.create_task(self.run())
        except (ValueError,OSError) as error: self.error=str(error)

    async def close(self):
        if self.task:
            self.task.cancel()
            try: await self.task
            except asyncio.CancelledError: pass

    async def run(self):
        async with httpx.AsyncClient(timeout=20,follow_redirects=False) as client:
            while True:
                try:
                    s=self.settings()
                    if not s: return
                    token=portal_credential(s['token_env'])
                    if not token: raise ValueError('Configured portal token environment variable is empty.')
                    headers={'Authorization':'Bearer '+token};base=s['base_url'].rstrip('/')
                    record=self.store.one('SELECT a.* FROM portal_assignments a LEFT JOIN portal_receipts r ON r.external_id=a.external_id WHERE r.external_id IS NULL ORDER BY a.created LIMIT 1')
                    if not record and not self.manager.active_job and self.manager.queue.empty():
                        response=await client.post(base+'/v1/clara/claim',headers=headers,json={'worker_id':s['worker_id'],'owner_key':s['owner_key']})
                        response.raise_for_status();assignment=response.json().get('assignment')
                        if assignment: record=self.accept(assignment,s)
                    if record:
                        if record['owner_key']!=s['owner_key']: raise ValueError('Stored assignment belongs to a different operator.')
                        job=self.store.job(record['job_id'])
                        last=self.store.one("SELECT data FROM events WHERE job_id=? AND kind='assistant' ORDER BY id DESC LIMIT 1",(job['id'],))
                        payload={'assignment_id':record['external_id'],'job_id':job['id'],'status':job['status'],
                            'terminal':job['status'] in TERMINAL,'reply':json.loads(last['data'])['text'] if last else '',
                            'usage':json.loads(job['usage']) if job['usage'] else None,
                            'artifacts':self.store.rows("SELECT id,name,size FROM files WHERE job_id=? AND kind='artifact'",(job['id'],))}
                        result=await client.post(base+'/v1/clara/result',headers=headers,json=payload)
                        result.raise_for_status()
                        if payload['terminal'] and result.json().get('acknowledged') is True:
                            self.store.execute('INSERT OR IGNORE INTO portal_receipts VALUES(?,?)',(record['external_id'],time.time()))
                    self.error=None
                except (ValueError,OSError,httpx.HTTPError) as error:
                    # Never log response bodies or authorization headers.
                    self.error=type(error).__name__+': portal unavailable or assignment rejected; inspect configuration and server logs.'
                await asyncio.sleep(10)
