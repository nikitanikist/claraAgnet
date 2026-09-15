"""Durable reservations for external writes. An uncertain write is never replayed."""
import json
import time
from .store import new_id
from .knowledge import job_scope, decode
from .workflows import canonical_hash


class Operations:
    def __init__(self,store): self.store=store

    def reserve(self,job,system,operation,key,request):
        if not all(isinstance(v,str) and 0<len(v)<=200 for v in [system,operation,key]):
            raise ValueError('Supply system, operation and stable business key (1–200 characters).')
        digest=canonical_hash(request);scope=job_scope(self.store,job)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM operations WHERE scope_key=? AND system=? AND operation=? AND external_key=?',
                           (scope,system,operation,key)).fetchone()
            if row:
                row=dict(row)
                if row['request_hash']!=digest:
                    raise ValueError('This business key already has a different request. Inspect the existing record.')
                if row['state']=='not_created':
                    db.execute("UPDATE operations SET state='uncertain',job_id=?,updated=? WHERE id=?",(job['id'],time.time(),row['id']))
                    db.execute('INSERT INTO operation_audit(operation_id,action,note,created) VALUES(?,?,?,?)',(row['id'],'retry_reserved','One operator-reviewed retry',time.time()))
                    return {'id':row['id'],'state':'uncertain','execute_allowed':True,'instruction':'One operator-reviewed retry reserved. Inspect remote state afterward.'}
                return {**row,'execute_allowed':False,'reason':'Existing reservation: read the remote state; do not repeat the write.'}
            oid=new_id();now=time.time()
            db.execute('INSERT INTO operations VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       (oid,job['id'],scope,system,operation,key,digest,'uncertain',None,None,now,now))
        return {'id':oid,'state':'uncertain','execute_allowed':True,
                'instruction':'One attempt is reserved. Inspect remote state after the attempt, including errors. The reservation itself is not authorization.'}

    def reconcile(self,job,oid,evidence_id,auto=None):
        op=self.store.one('SELECT * FROM operations WHERE id=? AND scope_key=?',(oid,job_scope(self.store,job)))
        proof=decode(self.store.one('SELECT e.* FROM evidence e JOIN jobs j ON j.id=e.job_id WHERE e.id=? AND j.conversation_id=?',
                                  (evidence_id,job['conversation_id'])),'payload')
        if not op or not proof or not proof['verified'] or proof['kind']!='remote_record':
            raise ValueError('Reconciliation requires runtime remote-record evidence in this conversation.')
        p=proof['payload']
        if op['state']=='confirmed' and json.loads(op['result'] or '{}').get('evidence_id')==evidence_id:
            return op
        # A proof matches by the observed on-page key or by the canonical reservation key it was recorded under.
        if p.get('system')!=op['system'] or op['external_key'] not in (p.get('external_key'),p.get('reservation_key')) or proof['created']<op['updated']:
            raise ValueError('Evidence does not match this reserved operation.')
        self.store.execute("UPDATE operations SET state='confirmed',remote_id=?,result=?,updated=? WHERE id=?",
                           (p['remote_id'],json.dumps({'evidence_id':evidence_id,**({'auto':auto} if auto else {})}),time.time(),oid))
        return self.store.one('SELECT * FROM operations WHERE id=?',(oid,))

    def list(self,job):
        return self.store.rows('SELECT * FROM operations WHERE scope_key=? ORDER BY created DESC LIMIT 100',(job_scope(self.store,job),))

    def confirm_absence(self,oid,note):
        if len(note.strip())<10: raise ValueError('Record where you checked and why the remote write is confirmed absent.')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            op=db.execute('SELECT * FROM operations WHERE id=?',(oid,)).fetchone()
            if not op or op['state']!='uncertain': raise ValueError('Only an uncertain operation can be resolved as not created.')
            retries=db.execute("SELECT COUNT(*) FROM operation_audit WHERE operation_id=? AND action='retry_reserved'",(oid,)).fetchone()[0]
            if retries>=1: raise ValueError('The reviewed retry was already used. Resolve this operation manually rather than repeating it.')
            db.execute("UPDATE operations SET state='not_created',updated=? WHERE id=?",(time.time(),oid))
            db.execute('INSERT INTO operation_audit(operation_id,action,note,created) VALUES(?,?,?,?)',(oid,'operator_confirmed_absence',note[:4000],time.time()))
        return {'state':'not_created','instruction':'One new attempt may be reserved with the same unchanged business key/request.'}
