"""Local, bounded tool evidence and crash recovery hints; never treat text as instructions."""
import base64
import json
import time
from .store import new_id
from .workflows import Workflows


def capture(config,store,job,data,tool_id):
    response=data.get('tool_response',data.get('tool_result',{}))
    if hasattr(response,'model_dump'): response=response.model_dump()
    if isinstance(response,str):
        try: response=json.loads(response)
        except ValueError: response={'text':response[:24000]}
    if isinstance(response,list): response={'content':response}
    if not isinstance(response,dict): response={'text':str(response)[:24000]}
    content=response.get('content',[])
    snippets=[];images=[]
    for block in content if isinstance(content,list) else []:
        if not isinstance(block,dict): continue
        if block.get('type')=='text': snippets.append(str(block.get('text',''))[:16000])
        if block.get('type')=='image' and config.settings().get('capture_evidence',True):
            raw=block.get('data','');mime=block.get('mimeType','')
            if mime not in {'image/png','image/jpeg'} or len(raw)>6_000_000 or len(images)>=1: continue
            try: binary=base64.b64decode(raw,validate=True)
            except (ValueError,TypeError): continue
            folder=config.data/'evidence';folder.mkdir(exist_ok=True)
            # Images are bounded separately from durable text/history and retained locally.
            old=sorted(folder.glob('*'),key=lambda p:p.stat().st_mtime)
            total=sum(p.stat().st_size for p in old)
            for p in old:
                if total+len(binary)<=100_000_000 and time.time()-p.stat().st_mtime<7*86400: break
                total-=p.stat().st_size;p.unlink()
            fid=new_id();path=folder/(fid+('.png' if mime=='image/png' else '.jpg'));path.write_bytes(binary)
            store.execute('INSERT INTO files VALUES(?,?,?,?,?,?,?,?)',(fid,job['conversation_id'],job['id'],'evidence',
                         'Desktop evidence'+path.suffix,str(path),len(binary),time.time()))
            images.append({'id':fid,'url':'/api/files/'+fid})
    text='\n'.join(snippets) or str(response.get('text',''))
    # Retain the same credential masking as the exported text diagnostics.
    from .diagnostics import redact_text,tool_diagnostic
    text=redact_text(text)
    wf=Workflows(store,config)
    observed={'tool':data.get('tool_name',''),'tool_id':tool_id,'text':text[:24000], 'images':images,
              'error':tool_diagnostic(data)['failed']}
    result=wf.evidence(job,'tool_observation',data.get('tool_name',''),observed,False)
    # Only the installed Windows bridge emits this schema; the model cannot mark a tool observation successful.
    if data.get('tool_name') in {'mcp__windows__ActAndVerify','mcp__windows__VerifyWindow'}:
        for snippet in snippets:
            try: value=json.loads(snippet)
            except ValueError: continue
            if value.get('clara_observation') and value.get('verified') and value.get('checks'):
                wf.evidence(job,'desktop_assertion','Windows accessible control check',value,not observed['error'])
    store.execute('INSERT OR REPLACE INTO execution_snapshots VALUES(?,?,?,?,?)',
                  (job['id'],data.get('tool_name'),json.dumps({'evidence_id':result['id'],**observed}),int(observed['error']),time.time()))
    return {'observation_id':result['id'],'images':images}
