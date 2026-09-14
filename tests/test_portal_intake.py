import asyncio
import json

import httpx
import pytest

from clara.agent import AgentManager
from clara.portal_contract import ContractViolation
from clara.portal_intake import PortalIntake
from clara.portal_transport import PortalReply, PortalTransport
from clara.workflows import Workflows
from test_portal_delivery import BASE, WORKER, setup, handler_for


def test_intake_preserves_all_messages_starts_exact_workflow_and_never_replays(tmp_path):
    config, store, claim, _ = setup(tmp_path)
    calls = []
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler_for(claim, calls))) as client:
            transport = PortalTransport(BASE, lambda: 'test', client=client, clock=lambda: 100)
            manager = AgentManager(config, store)
            assert manager.reserve_execution('portal')
            intake = PortalIntake(config, store, manager, transport, WORKER)
            result = await intake.start_claim(PortalReply(claim, 100), reservation_id='portal')
            job = store.job(result.local_job_id)
            assert manager.queue.get_nowait() == job['id']
            prompt = job['prompt']
            assert '"seq": 11' in prompt and '"seq": 12' in prompt
            state = Workflows(store, config).snapshot(job['conversation_id'])
            assert state['kind'] == 't1-closeout'
            assert state['context']['client_key'] == claim['closeout']['closeout_form_id']
            assert 'invoice' not in state['contract']
            assert len(state['contract']['documents']) == 3
            assert calls[-1][0] == 'clara-message-ack'
            again = await intake.start_claim(PortalReply({**claim, 'recovered': True}, 100), reservation_id='portal')
            assert again.recovered is True and again.local_job_id == job['id']
            assert manager.queue.empty() and len(store.rows('SELECT id FROM jobs')) == 1
    asyncio.run(scenario())


def test_intake_requires_reservation_and_refuses_different_owner_scope(tmp_path):
    config, store, claim, _ = setup(tmp_path)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler_for(claim, []))) as client:
            transport = PortalTransport(BASE, lambda: 'test', client=client, clock=lambda: 100)
            manager = AgentManager(config, store)
            intake = PortalIntake(config, store, manager, transport, WORKER)
            with pytest.raises(ContractViolation):
                await intake.start_claim(PortalReply(claim, 100), reservation_id='not-reserved')
            assert store.rows('SELECT id FROM jobs') == []
            manager.reserve_execution('portal')
            wrong = json.loads(json.dumps(claim))
            wrong['scope']['closeout_form_id'] = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
            with pytest.raises(ContractViolation):
                await intake.start_claim(PortalReply(wrong, 100), reservation_id='portal')
            assert manager.queue.empty() and store.rows('SELECT id FROM jobs') == []
    asyncio.run(scenario())
