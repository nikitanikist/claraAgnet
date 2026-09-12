import asyncio
import json

import pytest
from claude_agent_sdk import ResultMessage
from clara.agent import AgentManager
from clara.config import Config
from clara.diagnostics import tool_diagnostic, usable_snapshot
from clara.store import Store


@pytest.mark.parametrize('disabled', [False, 'false', 'False'])
def test_empty_windows_snapshot_gets_image_without_mutating_input(disabled):
    args = {'use_ui_tree': disabled, 'display': [0]}
    assert usable_snapshot('mcp__windows__Snapshot', args) == {**args, 'use_vision': True}
    assert 'use_vision' not in args
    for observed in ({}, {'use_ui_tree': True}, {'use_ui_tree': False, 'use_vision': 'true'}):
        assert usable_snapshot('mcp__windows__Snapshot', observed) == observed
    assert usable_snapshot('mcp__chrome__take_snapshot', args) == args


def test_errors_inside_successful_tool_responses_are_reported():
    result = {'tool_name': 'mcp__clara__run_command', 'hook_event_name': 'PostToolUse',
              'tool_response': {'content': [{'type': 'text', 'text': json.dumps({'exit_code': 1, 'output': 'Missing file'})}]}}
    assert tool_diagnostic(result, 150)['failed'] is True
    result['tool_response'] = {'isError': True, 'content': [{'type':'text', 'text':'Denied'}]}
    assert tool_diagnostic(result)['failed'] is True
    result.update(tool_name='mcp__windows__App', tool_response=['Application Example not found.'])
    assert tool_diagnostic(result)['failed'] is True
    result['tool_response'] = ['Switched to Example window.']
    assert tool_diagnostic(result)['failed'] is False


def test_tool_history_is_bounded_and_keeps_error_tail_but_not_images_or_known_secrets():
    result = tool_diagnostic({'tool_name':'mcp__windows__Snapshot', 'hook_event_name':'PostToolUse',
        'tool_response': {'content': [
            {'type':'text', 'text':'Bearer sensitive_token ' + ('x' * 10000) + ' END EVIDENCE'},
            {'type':'image', 'data':'SENSITIVE_IMAGE_BYTES', 'mimeType':'image/png'}]}}, 250)
    serialized = json.dumps(result)
    assert result['duration_ms'] == 250 and result['output_truncated'] is True
    assert result['image_count'] == 1
    assert len(result['output_excerpt']) < 6100
    assert 'END EVIDENCE' in serialized
    assert 'sensitive_token' not in serialized and 'SENSITIVE_IMAGE_BYTES' not in serialized


def test_hooks_save_actual_adjusted_call_output_and_explain_turn_exhaustion(tmp_path, monkeypatch):
    class SDKDouble:
        def __init__(self, options):
            self.options = options
            assert options.effort == 'medium'
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def query(self, prompt): pass
        async def receive_response(self):
            pre = self.options.hooks['PreToolUse'][0].hooks[0]
            post = self.options.hooks['PostToolUse'][0].hooks[0]
            call = {'tool_name':'mcp__windows__Snapshot', 'tool_input':{'use_ui_tree':'false'}}
            corrected = await pre(call, 'observe', {})
            assert corrected['hookSpecificOutput']['updatedInput']['use_vision'] is True
            await post({**call, 'hook_event_name':'PostToolUse', 'tool_response':[
                {'type':'text','text':'Focused window: Example'}, {'type':'image','data':'image-bytes'}]}, 'observe', {})
            yield ResultMessage(subtype='error_max_turns', duration_ms=1, duration_api_ms=1,
                is_error=True, num_turns=41, session_id='test', errors=['Reached maximum number of turns (40)'])
    async def auth(): return {'connected':True, 'plan':'max'}
    monkeypatch.setattr('clara.agent.ClaudeSDKClient', SDKDouble)
    monkeypatch.setattr('clara.agent.auth_status', auth)
    async def scenario():
        cfg=Config(tmp_path);cfg.initialize();store=Store(tmp_path/'test.sqlite')
        cid=store.create_conversation()['id'];job=store.create_job(cid, 'UI test', 'ask', [])
        await AgentManager(cfg,store).execute(job)
        events=store.events(cid)
        call=next(e['data'] for e in events if e['kind']=='tool')
        done=next(e['data'] for e in events if e['kind']=='tool_done')
        assert json.loads(call['input'])['use_vision'] is True
        assert done['output_excerpt']=='Focused window: Example'
        assert done['image_count']==1 and done['duration_ms'] >= 0
        assert store.job(job['id'])['status']=='failed'
        assert 'task is incomplete' in events[-1]['data']['message']
        assert 'Last tool requested: mcp__windows__Snapshot' in events[-1]['data']['message']
    asyncio.run(scenario())
