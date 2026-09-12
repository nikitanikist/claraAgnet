import asyncio
import json

import pytest
from claude_agent_sdk import ClaudeAgentOptions, ResultMessage
from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport
from fastapi.testclient import TestClient
from pydantic import ValidationError

from clara.agent import AgentManager
from clara.app import SettingsInput, create_app
from clara.auth import cli_path
from clara.config import Config
from clara.production_api import BudgetInput
from clara.store import Store
from clara.workflows import Workflows


@pytest.mark.parametrize('turns', [None, 500, 5000])
def test_operator_can_save_and_reload_finite_or_unlimited_caps(tmp_path, turns):
    class Manager:
        def __init__(self, *args): self.active_job=None; self.queue=asyncio.Queue()
        async def start(self): pass
        async def close(self): pass
    cfg=Config(tmp_path/'data')
    app=create_app(cfg,manager_factory=Manager,access_token='test-only')
    with TestClient(app,base_url='http://127.0.0.1:8876') as client:
        client.headers['x-clara-request']='1'
        client.post('/api/session',json={'token':'test-only'}).raise_for_status()
        response=client.put('/api/settings',json={'max_turns':turns})
        assert response.status_code==200
        assert client.get('/api/settings').json()['max_turns']==turns
        assert Config(cfg.data).settings()['max_turns']==turns
        cid=app.state.store.create_conversation()['id']
        client.post(f'/api/conversations/{cid}/workflow',json={'kind':'t1-print','context':{
            'client_key':'test','year':'2025','members':['Test Person']}}).raise_for_status()
        response=client.put(f'/api/conversations/{cid}/workflow/budget',json={
            'max_turns':turns,'task_timeout_minutes':30,'max_budget_usd':10,
            'note':'Operator changed the turn limit to continue the existing test.'})
        assert response.status_code==200
        state=Workflows(Store(cfg.data/'clara.sqlite3'),cfg).snapshot(cid)
        assert state['limits']['max_turns']==turns
        assert state['budget']['remaining_turns']==turns
        assert state['limits']['task_timeout_minutes']==30 and state['limits']['max_budget_usd']==10
        assert app.state.store.one("SELECT * FROM events WHERE conversation_id=? AND kind='workflow_budget'",(cid,))


@pytest.mark.parametrize('turns', [0, -1, 1.5])
def test_invalid_turn_caps_are_rejected(turns):
    with pytest.raises(ValidationError): SettingsInput(max_turns=turns)
    with pytest.raises(ValidationError): BudgetInput(max_turns=turns,task_timeout_minutes=20,note='test')


@pytest.mark.parametrize('per_request,total,used,expected', [
    (None,None,101,None), (None,500,101,399), (500,None,101,500),
    (500,700,101,500), (100,None,0,100), (None,100,101,'blocked'),
])
def test_resume_combines_caps_without_losing_progress(tmp_path,monkeypatch,per_request,total,used,expected):
    cfg=Config(tmp_path/'data');cfg.initialize()
    cfg.save_settings({**cfg.settings(),'max_turns':total,'max_budget_usd':10})
    store=Store(cfg.data/'clara.sqlite3');wf=Workflows(store,cfg)
    cid=store.create_conversation()['id'];old=store.create_job(cid,'Original T1 task','ask',[])
    wf.begin(old,'t1-print',{'client_key':'test','year':'2025','members':['Test Person']})
    wf.checkpoint(old,'intake',[],note='Original intake was verified.')
    store.execute('UPDATE jobs SET status=?,usage=? WHERE id=?',('failed',json.dumps({
        'turns':used,'sdk_estimated_usd':2,'wall_duration_ms':1000,'coverage':'reported'}),old['id']))
    store.execute('UPDATE conversations SET session_id=? WHERE id=?',('saved-session',cid))
    cfg.save_settings({**cfg.settings(),'max_turns':per_request})
    job=store.create_job(cid,'Resume the existing test','ask',[])
    observed=[]
    class SDK:
        def __init__(self,options): self.options=options;observed.append(options)
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def query(self,prompt): assert 'Original intake was verified.' in prompt
        async def receive_response(self):
            yield ResultMessage(subtype='success',duration_ms=1,duration_api_ms=1,is_error=False,
                num_turns=1,session_id='saved-session',usage={'input_tokens':1,'output_tokens':1},total_cost_usd=0.01)
    async def auth(): return {'connected':True,'plan':'test'}
    monkeypatch.setattr('clara.agent.ClaudeSDKClient',SDK)
    monkeypatch.setattr('clara.agent.auth_status',auth)
    if expected=='blocked':
        with pytest.raises(ValueError,match='budget exhausted'): asyncio.run(AgentManager(cfg,store).execute(job))
        assert not observed
    else:
        asyncio.run(AgentManager(cfg,store).execute(job))
        options=observed[0]
        assert options.max_turns==expected and options.resume=='saved-session'
        assert options.max_budget_usd==8
        assert ('No Clara model-turn limit' in options.system_prompt)==(expected is None)
        state=wf.snapshot(cid)
        assert state['stages']['intake']['status']=='verified'
        assert state['budget']['used']['turns']==used+1
        assert state['budget']['used']['usd']==pytest.approx(2.01)


@pytest.mark.parametrize('exhausted', ['time','cost'])
def test_unlimited_turns_do_not_disable_time_or_cost_budget(tmp_path,monkeypatch,exhausted):
    cfg=Config(tmp_path/'data');cfg.initialize()
    cfg.save_settings({**cfg.settings(),'max_turns':None,'task_timeout_minutes':1,'max_budget_usd':1})
    store=Store(cfg.data/'clara.sqlite3');wf=Workflows(store,cfg)
    cid=store.create_conversation()['id'];old=store.create_job(cid,'Test','ask',[])
    wf.begin(old,'general',{})
    store.execute('UPDATE jobs SET status=?,usage=? WHERE id=?',('failed',json.dumps({
        'turns':1001,'sdk_estimated_usd':1 if exhausted=='cost' else 0,
        'wall_duration_ms':60000 if exhausted=='time' else 1,'coverage':'reported'}),old['id']))
    async def auth(): return {'connected':True,'plan':'test'}
    monkeypatch.setattr('clara.agent.auth_status',auth)
    job=store.create_job(cid,'Continue','ask',[])
    with pytest.raises(ValueError,match='budget exhausted'): asyncio.run(AgentManager(cfg,store).execute(job))


def test_sdk_omits_max_turns_argument_when_no_cap_is_configured():
    for turns in [None,500]:
        options=ClaudeAgentOptions(cli_path=cli_path(),max_turns=turns)
        command=SubprocessCLITransport(prompt='test',options=options)._build_command()
        if turns is None: assert '--max-turns' not in command
        else: assert command[command.index('--max-turns')+1]=='500'
