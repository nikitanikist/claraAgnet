"""Small evidence indexes, with explicit detail retrieval and conversation scope."""
import json
from .knowledge import decode


def evidence_index(store,cid,kind=None,tool=None,limit=10,before=None):
    if not isinstance(limit,int) or isinstance(limit,bool) or not 1<=limit<=20:
        raise ValueError('Evidence page size must be between 1 and 20.')
    sql='SELECT e.* FROM evidence e JOIN jobs j ON j.id=e.job_id WHERE j.conversation_id=?'
    values=[cid]
    if kind:
        sql+=' AND e.kind=?';values.append(kind)
    elif not tool: sql+=" AND e.kind!='tool_observation'"
    if tool: sql+=' AND e.kind=? AND e.subject=?';values+=['tool_observation',tool]
    if before:
        anchor=store.one('SELECT e.created,e.id FROM evidence e JOIN jobs j ON j.id=e.job_id WHERE e.id=? AND j.conversation_id=?',(before,cid))
        if not anchor: raise ValueError('Evidence cursor is not in this conversation.')
        sql+=' AND (e.created<? OR (e.created=? AND e.id<?))';values += [anchor['created'],anchor['created'],anchor['id']]
    rows=store.rows(sql+' ORDER BY e.created DESC,e.id DESC LIMIT ?',(*values,limit+1))
    records=[]
    for raw in rows[:limit]:
        row=decode(raw,'payload');p=row['payload']
        item={k:row[k] for k in ('id','kind','subject','verified','created')}
        item['subject']=str(item['subject'])[:200]
        item['summary']={k:(str(p[k])[:300] if isinstance(p[k],str) else p[k]) for k in
            ('member','year','document_type','pages','sha256','system','remote_id','status','tool','error')
            if k in p and isinstance(p[k],(str,int,float,bool))}
        records.append(item)
    return {'records':records,'next_cursor':records[-1]['id'] if len(rows)>limit else None,
            'note':'Compact index. Use get_evidence for a specific record. Tool observations are excluded unless kind or tool selects them.'}


def evidence_detail(store,cid,id,offset=0,length=6000):
    if not isinstance(offset,int) or isinstance(offset,bool) or offset<0 or not isinstance(length,int) or isinstance(length,bool) or not 100<=length<=12000:
        raise ValueError('Use a nonnegative offset and a detail length between 100 and 12000 characters.')
    row=decode(store.one('SELECT e.* FROM evidence e JOIN jobs j ON j.id=e.job_id WHERE e.id=? AND j.conversation_id=?',(id,cid)),'payload')
    if not row: raise ValueError('Evidence is not in this conversation.')
    payload=json.dumps(row['payload'],ensure_ascii=False)
    if offset>len(payload): raise ValueError('Offset is beyond this evidence record.')
    return {**{k:row[k] for k in ('id','kind','subject','verified','created')},
            'payload_text':payload[offset:offset+length],'offset':offset,'total_chars':len(payload),
            'next_offset':offset+length if offset+length<len(payload) else None}
