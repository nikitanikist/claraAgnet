import asyncio
import json
from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, StreamEvent
from clara.agent import AgentManager, SDK_MESSAGE_BUFFER_BYTES
from clara.config import Config
from clara.store import Store
from clara.instance import single_instance


def test_exclusive_instance_lock_releases(tmp_path):
    with single_instance(tmp_path):
        with pytest.raises(RuntimeError):
            with single_instance(tmp_path):
                pass
    with single_instance(tmp_path):
        pass


@pytest.mark.parametrize('fail', [False, True])
def test_sdk_adapter_stream_session_and_error_state(tmp_path, monkeypatch, fail):
    captured = {}
    class SDKDouble:
        def __init__(self, options):
            captured['options'] = options
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def query(self, prompt): captured['prompt'] = prompt
        async def receive_response(self):
            yield StreamEvent(uuid='stream', session_id='session-1', event={'type':'content_block_delta','delta':{'type':'text_delta','text':'Hello'}}, parent_tool_use_id=None)
            yield AssistantMessage(content=[TextBlock(text='Hello')], model='test')
            yield ResultMessage(subtype='error_during_execution' if fail else 'success', duration_ms=10,
                duration_api_ms=5, is_error=fail, num_turns=1, session_id='session-1',
                result='Failed to authenticate: OAuth expired' if fail else 'Hello',
                usage={'input_tokens':10,'output_tokens':1})
    async def auth(): return {'connected': True, 'plan': 'max'}
    monkeypatch.setattr('clara.agent.ClaudeSDKClient', SDKDouble)
    monkeypatch.setattr('clara.agent.auth_status', auth)
    async def scenario():
        cfg=Config(tmp_path);cfg.initialize();store=Store(tmp_path/'test.sqlite')
        cfg.save_settings({**cfg.settings(), 'max_budget_usd': 0.05})
        cid=store.create_conversation()['id'];job=store.create_job(cid,'hello','ask',[])
        manager=AgentManager(cfg,store)
        await manager.execute(job)
        assert store.conversation(cid)['session_id']=='session-1'
        assert store.job(job['id'])['status']==('failed' if fail else 'completed')
        assert [e['kind'] for e in store.events(cid)].count('delta') == 1
        assert json.loads((cfg.data/'model-health.json').read_text())['needs_login'] is fail
        opts=captured['options']
        assert opts.max_buffer_size == SDK_MESSAGE_BUFFER_BYTES
        assert opts.fallback_model is None
        assert opts.max_budget_usd == 0.05
        assert 'Stop' in opts.hooks
        assert opts.strict_mcp_config is True
        assert opts.setting_sources==['project']
        assert opts.permission_mode=='default'
        assert opts.skills=='all'
        assert 'Bash' not in opts.tools
        blocked = await opts.hooks['PreToolUse'][0].hooks[0]({'tool_name':'Read','tool_input':{'file_path':'/outside/file'}},'test',{})
        assert blocked['hookSpecificOutput']['permissionDecision']=='deny'
    asyncio.run(scenario())
