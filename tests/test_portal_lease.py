from datetime import datetime, timedelta, timezone

import pytest

from clara.portal_lease import AttemptIdentity, ExecutionLease, LeaseLost


IDENTITY = AttemptIdentity('job-1', 'worker-1', 1, 42)
SERVER_TIME = datetime(2026, 9, 14, tzinfo=timezone.utc)


def lease_fixture():
    now = [100.0]
    lease = ExecutionLease(IDENTITY, clock=lambda: now[0])
    return lease, now


def renew(lease, sent=100.0, identity=IDENTITY, duration=120):
    return lease.acknowledge(identity, expires_at=SERVER_TIME + timedelta(seconds=duration),
                             server_time=SERVER_TIME, request_started=sent)


def test_silence_fences_before_server_expiry_and_cannot_be_revived():
    lease, now = lease_fixture()
    renew(lease)
    now[0] = 214.99
    lease.assert_active()
    now[0] = 215
    with pytest.raises(LeaseLost, match='expired'):
        lease.assert_active()
    with pytest.raises(LeaseLost):
        renew(lease, sent=215)
    assert lease.remaining_seconds == 0


def test_only_acknowledgement_renews_and_network_delay_consumes_lease():
    lease, now = lease_fixture()
    with pytest.raises(LeaseLost, match='No acknowledged'):
        lease.assert_active()
    now[0] = 130
    renew(lease)
    assert lease.remaining_seconds == 85
    renew(lease, sent=130)
    assert lease.remaining_seconds == 115
    # A slow response from an older request cannot change that deadline.
    assert renew(lease, sent=110) is False
    assert lease.remaining_seconds == 115


@pytest.mark.parametrize('identity', [
    AttemptIdentity('job-other', 'worker-1', 1, 42),
    AttemptIdentity('job-1', 'worker-other', 1, 42),
    AttemptIdentity('job-1', 'worker-1', 2, 42),
    AttemptIdentity('job-1', 'worker-1', 1, 43),
])
def test_ack_must_match_all_attempt_fields(identity):
    lease, _ = lease_fixture()
    renew(lease)
    with pytest.raises(LeaseLost, match='different attempt'):
        renew(lease, identity=identity)
    with pytest.raises(LeaseLost):
        renew(lease)


def test_delayed_first_ack_and_unbounded_server_lease():
    lease, now = lease_fixture()
    now[0] = 220
    with pytest.raises(LeaseLost, match='before its acknowledgement'):
        renew(lease)
    lease, _ = lease_fixture()
    renew(lease, duration=3600)
    assert lease.remaining_seconds == 115


def test_lease_does_not_depend_on_windows_wall_clock():
    lease, _ = lease_fixture()
    server = datetime(2001, 1, 1, tzinfo=timezone(timedelta(hours=-5)))
    lease.acknowledge(IDENTITY, expires_at=server + timedelta(seconds=90),
                      server_time=server, request_started=100)
    assert lease.remaining_seconds == 85


def test_stop_and_invalid_ack_fail_closed():
    lease, _ = lease_fixture()
    renew(lease)
    lease.fence('Stop requested.')
    with pytest.raises(LeaseLost, match='Stop requested'):
        renew(lease)
    lease, _ = lease_fixture()
    with pytest.raises(LeaseLost, match='server timestamps'):
        lease.acknowledge(IDENTITY, expires_at=datetime(2026, 9, 14),
                          server_time=SERVER_TIME, request_started=100)


@pytest.mark.parametrize('number', [True, 0, -1, 1.5, '42'])
def test_invalid_identity_is_rejected(number):
    with pytest.raises(ValueError):
        AttemptIdentity('job-1', 'worker-1', 1, number)


def test_fenced_job_stops_before_model_query(tmp_path, monkeypatch):
    import asyncio
    import json
    from clara.agent import AgentManager
    from clara.config import Config
    from clara.store import Store

    async def scenario():
        cfg = Config(tmp_path)
        cfg.initialize()
        store = Store(tmp_path / 'test.sqlite')
        job = store.create_job(store.create_conversation()['id'], 'Find a file', 'autonomous', [])
        manager = AgentManager(cfg, store)
        lease, _ = lease_fixture()
        renew(lease)
        lease.fence('Stop requested.')
        manager.execution_guards[job['id']] = lease
        def forbidden_sdk(**kwargs):
            pytest.fail('A fenced attempt must not create a model client')
        monkeypatch.setattr('clara.agent.ClaudeSDKClient', forbidden_sdk)
        with pytest.raises(LeaseLost):
            await manager.execute(job)
        usage = json.loads(store.job(job['id'])['usage'])
        assert usage['total_tokens'] == 0
    asyncio.run(scenario())


def test_answer_after_fencing_does_not_resume_action(tmp_path):
    import asyncio
    from clara.agent import AgentManager
    from clara.config import Config
    from clara.store import Store

    async def scenario():
        cfg = Config(tmp_path)
        cfg.initialize()
        store = Store(tmp_path / 'test.sqlite')
        job = store.create_job(store.create_conversation()['id'], 'Find a file', 'ask', [])
        manager = AgentManager(cfg, store)
        lease, _ = lease_fixture()
        renew(lease)
        manager.execution_guards[job['id']] = lease
        pending = asyncio.create_task(manager.request_input(job, 'approval', {'tool': 'Click'}))
        await asyncio.sleep(0)
        request_id = next(iter(manager.pending))
        lease.fence('Stop requested.')
        manager.answer(request_id, 'allow')
        with pytest.raises(LeaseLost):
            await pending
        assert not manager.pending
        assert not any(e['kind'] == 'answer' for e in store.events(job['conversation_id']))
    asyncio.run(scenario())


def test_in_process_tool_cannot_bypass_expired_lease(tmp_path, monkeypatch):
    import asyncio
    from clara.config import Config
    from clara.store import Store
    from clara.tools import tool_server

    cfg = Config(tmp_path)
    cfg.initialize()
    store = Store(tmp_path / 'test.sqlite')
    job = store.create_job(store.create_conversation()['id'], 'Write test', 'autonomous', [])
    lease, now = lease_fixture()
    renew(lease)
    monkeypatch.setattr('clara.tools.create_sdk_mcp_server', lambda **kwargs: kwargs)
    server = tool_server(cfg, store, job, None, execution_guard=lease.assert_active)
    writer = next(tool for tool in server['tools'] if tool.name == 'write_text')
    now[0] = 216
    with pytest.raises(LeaseLost):
        asyncio.run(writer.handler({'path': 'must-not-exist.txt', 'content': 'test'}))
    assert not (cfg.workspace / 'must-not-exist.txt').exists()


def test_sdk_hooks_and_final_result_remain_fenced_in_autonomous_mode(tmp_path, monkeypatch):
    import asyncio
    import json
    from claude_agent_sdk import PermissionResultDeny, ResultMessage
    from clara.agent import AgentManager
    from clara.config import Config
    from clara.store import Store

    lease, _ = lease_fixture()
    renew(lease)
    observed = []

    class SDKDouble:
        def __init__(self, options): self.options = options
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def query(self, prompt): pass
        async def receive_response(self):
            lease.fence('Lease lost during execution.')
            hook = self.options.hooks['PreToolUse'][0].hooks[0]
            denied = await hook({'tool_name': 'mcp__windows__Click', 'tool_input': {}}, 'click-1', {})
            assert denied['hookSpecificOutput']['permissionDecision'] == 'deny'
            permission = await self.options.can_use_tool('mcp__windows__Click', {}, {})
            assert isinstance(permission, PermissionResultDeny)
            observed.append('hooks checked')
            yield ResultMessage(subtype='success', duration_ms=10, duration_api_ms=5,
                                is_error=False, num_turns=1, session_id='lease-test-session',
                                result='Done', usage={'input_tokens': 10, 'output_tokens': 1})

    async def auth(): return {'connected': True, 'plan': 'test'}
    monkeypatch.setattr('clara.agent.ClaudeSDKClient', SDKDouble)
    monkeypatch.setattr('clara.agent.auth_status', auth)

    async def scenario():
        cfg = Config(tmp_path)
        cfg.initialize()
        store = Store(tmp_path / 'test.sqlite')
        job = store.create_job(store.create_conversation()['id'], 'Test', 'autonomous', [])
        manager = AgentManager(cfg, store)
        manager.execution_guards[job['id']] = lease
        with pytest.raises(LeaseLost):
            await manager.execute(job)
        assert observed == ['hooks checked']
        assert store.job(job['id'])['status'] != 'completed'
        # Actual usage is retained even when the success result is fenced out.
        assert json.loads(store.job(job['id'])['usage'])['total_tokens'] == 11
    asyncio.run(scenario())
