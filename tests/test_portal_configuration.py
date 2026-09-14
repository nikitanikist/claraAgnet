import asyncio
import json

import pytest

from clara.agent import AgentManager
from clara.portal import PortalWorker
from test_portal_delivery import BASE, WORKER, setup


def settings(config, **changes):
    body = {'enabled':True, 'protocol_version':1, 'base_url':BASE,
            'worker_id':WORKER, 'token_env':'CLARA_PORTAL_WORKER_KEY',
            'authentication_reviewed':True, **changes}
    (config.data / 'portal.json').write_text(json.dumps(body))
    return body


def test_v1_worker_settings_use_enrolled_identity_without_legacy_owner(tmp_path):
    config, store, _, _ = setup(tmp_path)
    expected = settings(config)
    worker = PortalWorker(config, store, AgentManager(config, store))
    assert worker.settings() == expected
    settings(config, enabled=False, worker_id='not-enrolled')
    assert worker.settings() is None


@pytest.mark.parametrize('changes', [
    {'protocol_version':True}, {'protocol_version':2}, {'worker_id':'unknown'},
    {'base_url':'http://example.com/functions/v1'}, {'base_url':BASE+'?key=unsafe'},
    {'token_env':'MODEL_KEY'}, {'authentication_reviewed':False},
    {'windows_handoff': {'qualified':True}},
    {'windows_handoff': {'exclusive_session':'yes'}},
    {'windows_handoff': {'exclusive_session':True, 'qualified':1}},
    {'windows_handoff': {'exclusive_session':True, 'ignore_unknowns':True}},
])
def test_unreviewed_or_misdirected_configuration_never_starts(tmp_path, changes):
    config, store, _, _ = setup(tmp_path)
    settings(config, **changes)
    worker = PortalWorker(config, store, AgentManager(config, store))
    with pytest.raises(ValueError):
        worker.settings()


def test_version_dispatch_starts_and_closes_v1_runtime_without_legacy_polling(tmp_path, monkeypatch):
    config, store, _, _ = setup(tmp_path)
    settings(config)
    calls = []
    class Runtime:
        def __init__(self, cfg, db, manager, transport, worker_id):
            self.transport, self.error = transport, 'Retained recovery hold'
            calls.append((transport.base_url, worker_id))
        async def start(self):
            self.task = asyncio.create_task(asyncio.Event().wait())
        async def close(self):
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            await self.transport.close()
            calls.append('closed')
    monkeypatch.setattr('clara.portal_runtime.PortalRuntime', Runtime)
    async def scenario():
        worker = PortalWorker(config, store, AgentManager(config, store))
        await worker.start()
        assert worker.v1 is not None and worker.task is worker.v1.task
        assert worker.error == 'Retained recovery hold'
        await worker.close()
        assert worker.task.done()
        assert calls == [(BASE, WORKER), 'closed']
    asyncio.run(scenario())
