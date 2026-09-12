"""Regressions from delivery trials, using only synthetic local fixtures."""
import asyncio
import base64
import json
from pathlib import Path

import pytest
from claude_agent_sdk import ClaudeAgentOptions
from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport
from fastapi.testclient import TestClient

from clara.agent import AgentManager
from clara.app import create_app
from clara.auth import cli_path
from clara.config import Config
from clara.diagnostics import tool_diagnostic
from clara.evidence import capture
from clara.evidence_index import evidence_index, evidence_detail
from clara.questions import question_data
from clara.store import Store
from clara.tools import tool_server
from clara.usage import with_wait_timing, normalize_usage
from clara.workflows import Workflows


@pytest.fixture
def env(tmp_path):
    cfg=Config(tmp_path/'data');cfg.initialize();s=Store(cfg.data/'test.sqlite')
    job=s.create_job(s.create_conversation()['id'],'Synthetic delivery','autonomous',[])
    return cfg,s,job


@pytest.mark.parametrize('shape',['flat','string','list','mcp','sdk'])
def test_bridge_verification_survives_sdk_envelopes(env,shape):
    cfg,s,j=env
    proof={'clara_observation':True,'verified':True,'checks':[{'passed':True,'text':'Test Window'}]}
    block={'type':'text','text':json.dumps(proof)}
    response={'flat':proof,'string':json.dumps(proof),'list':[block],'mcp':{'content':[block]},'sdk':[json.dumps(proof)]}[shape]
    capture(cfg,s,j,{'tool_name':'mcp__windows__VerifyWindow','tool_response':response},'test')
    assertions=s.rows("SELECT * FROM evidence WHERE kind='desktop_assertion'")
    assert len(assertions)==1 and assertions[0]['verified']==1
    assert 'Test Window' in assertions[0]['payload']


@pytest.mark.parametrize('proof',[{'clara_observation':True,'verified':True,'checks':None},
    {'clara_observation':True,'verified':True,'checks':[None]},
    {'clara_observation':True,'verified':True,'checks':[{'passed':False}]},
    {'clara_observation':True,'verified':False,'checks':[{'passed':True}]}])
def test_malformed_or_failed_assertions_cannot_become_verified(env,proof):
    cfg,s,j=env
    capture(cfg,s,j,{'tool_name':'mcp__windows__VerifyWindow','tool_response':json.dumps(proof)},'test')
    assert not s.rows("SELECT * FROM evidence WHERE kind='desktop_assertion' AND verified=1")


def test_error_envelope_prevents_assertion_and_untrusted_tool_cannot_promote(env):
    cfg,s,j=env
    response={'isError':True,'content':[{'type':'text','text':json.dumps({'clara_observation':True,'verified':True,'checks':[{'passed':True}]})}]}
    capture(cfg,s,j,{'tool_name':'mcp__windows__VerifyWindow','tool_response':response},'test')
    response['isError']=False
    capture(cfg,s,j,{'tool_name':'mcp__chrome__evaluate_script','tool_response':response},'test2')
    assert not s.rows("SELECT * FROM evidence WHERE kind='desktop_assertion' AND verified=1")


def test_sdk_image_source_is_saved_without_base64_in_history(env):
    cfg,s,j=env
    image=base64.b64encode(b'synthetic-png-bytes').decode()
    data={'tool_name':'mcp__chrome__take_screenshot','tool_response':[
        {'type':'image','source':{'type':'base64','data':image,'media_type':'image/png'}}]}
    result=capture(cfg,s,j,data,'test')
    assert len(result['images'])==1 and tool_diagnostic(data)['image_count']==1
    file=s.one('SELECT * FROM files WHERE id=?',(result['images'][0]['id'],))
    assert Path(file['path']).read_bytes()==b'synthetic-png-bytes'
    assert image not in s.one('SELECT * FROM evidence WHERE id=?',(result['observation_id'],))['payload']


@pytest.mark.parametrize('tool,text',[
    ('mcp__chrome__drag','Error: Element with uid test-13 is not present in the current snapshot'),
    ('mcp__clara__list_evidence','Error: result (50123 characters) exceeds maximum allowed tokens'),
    ('mcp__clara__run_command',json.dumps({'clara_tool_error':True,'message':'Synthetic failure'})),
])
def test_flat_errors_are_visible_as_failed(tool,text):
    assert tool_diagnostic({'tool_name':tool,'tool_response':[text]})['failed']


def test_evidence_index_is_small_paginates_and_respects_scope(env):
    cfg,s,j=env;w=Workflows(s,cfg);cid=j['conversation_id']
    business=[]
    for i in range(25):
        e=w.evidence(j,'remote_record',f'Synthetic result {i}',{'status':'verified','body':'x'*50000},True)
        business.append(e['id'])
        w.evidence(j,'tool_observation','mcp__chrome__take_snapshot',{'text':'x'*60000},False)
    collected=[];cursor=None
    while True:
        page=evidence_index(s,cid,before=cursor)
        assert len(json.dumps(page))<10000 and len(page['records'])<=10
        assert all('body' not in r['summary'] and r['kind']=='remote_record' for r in page['records'])
        collected.extend(r['id'] for r in page['records']);cursor=page['next_cursor']
        if cursor is None: break
    assert sorted(collected)==sorted(business)
    observations=evidence_index(s,cid,tool='mcp__chrome__take_snapshot',limit=2)
    assert len(observations['records'])==2 and observations['next_cursor']
    parts=[];offset=0
    while offset is not None:
        chunk=evidence_detail(s,cid,business[0],offset,length=6000)
        assert len(chunk['payload_text'])<=6000
        parts.append(chunk['payload_text']);offset=chunk['next_offset']
    assert json.loads(''.join(parts))['body']=='x'*50000
    other=s.create_conversation()['id']
    with pytest.raises(ValueError,match='conversation'): evidence_detail(s,other,business[0])
    with pytest.raises(ValueError,match='conversation'): evidence_index(s,other,before=business[0])
    for limit in [0,True,21]:
        with pytest.raises(ValueError): evidence_index(s,cid,limit=limit)
    with pytest.raises(ValueError): evidence_detail(s,cid,business[0],length=50000)


def test_structured_questions_reach_real_pending_and_error_survives_flattening(env,monkeypatch):
    cfg,s,j=env
    monkeypatch.setattr('clara.tools.create_sdk_mcp_server',lambda **kwargs:kwargs)
    manager=AgentManager(cfg,s)
    defs=tool_server(cfg,s,j,manager.request_input)['tools']
    ask=next(t for t in defs if t.name=='ask_user')
    async def scenario():
        body={'question':'Which test folder should I use?','context':'The PDFs are ready. Existing files will stay in place.',
            'details':'Synthetic background.\n\nNo client records here.',
            'choices':[{'label':'New test folder','answer':'Create a new test folder.'}]}
        task=asyncio.create_task(ask.handler(body))
        await asyncio.sleep(0)
        pending=manager.pending_requests(j['conversation_id'])
        assert len(pending)==1 and pending[0]['data']==body and not task.done()
        manager.answer(pending[0]['request_id'],'Use my test folder.\nKeep its name.')
        result=await task
        assert 'Keep its name.' in str(result)
        assert not manager.pending_requests(j['conversation_id'])
        error=await ask.handler({'question':''})
        assert error['isError']
        assert tool_diagnostic({'tool_name':'mcp__clara__ask_user','tool_response':[error['content'][0]['text']]})['failed']
    asyncio.run(scenario())
    assert question_data({'question':'Legacy line one.\n\nLine two.'})['question'].count('\n')==2
    with pytest.raises(ValueError): question_data({'question':'Which?','choices':[{'label':'Invalid'}]})


def test_wait_timing_merges_overlaps_clips_at_cancel_and_does_not_mix_jobs(env):
    cfg,s,j=env
    def event(kind,rid,at,job=j):
        eid=s.event(job['conversation_id'],job['id'],kind,{'request_id':rid})
        s.execute('UPDATE events SET created=? WHERE id=?',(at,eid))
    event('question','a',90);event('approval','b',110);event('answer','a',120);event('answer','b',130)
    event('question','c',140)  # cancelled while waiting, capped at task end
    other=s.create_job(j['conversation_id'],'Other','ask',[])
    event('question','other',100,other)
    result=with_wait_timing(s,j,{'wall_duration_ms':50000},150)
    assert result['user_wait_ms']==40000 and result['active_duration_ms']==10000
    assert normalize_usage(result)['user_wait_ms']==40000
    assert normalize_usage({'version':2,**result})['active_duration_ms']==10000
    assert with_wait_timing(s,j,{},150)=={}


def test_effort_settings_persist_and_sdk_receives_supported_argument(env):
    cfg,s,j=env
    class Manager:
        active_job=None
        def __init__(self,*args): self.queue=asyncio.Queue()
        async def start(self): pass
        async def close(self): pass
    app=create_app(cfg,manager_factory=Manager,access_token='synthetic-only')
    with TestClient(app,base_url='http://127.0.0.1:8876') as client:
        client.headers['x-clara-request']='1'
        client.post('/api/session',json={'token':'synthetic-only'}).raise_for_status()
        assert client.get('/api/settings').json()['reasoning_effort']=='medium'
        for effort in ['low','medium','high','xhigh','max']:
            client.put('/api/settings',json={'model':'opus','reasoning_effort':effort}).raise_for_status()
            assert cfg.settings()['reasoning_effort']==effort and cfg.settings()['model']=='opus'
            command=SubprocessCLITransport(prompt='synthetic',options=ClaudeAgentOptions(cli_path=cli_path(),effort=effort))._build_command()
            assert command[command.index('--effort')+1]==effort
        assert client.put('/api/settings',json={'reasoning_effort':'invalid'}).status_code==422
