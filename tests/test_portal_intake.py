import asyncio
import json

import httpx
import pytest

from clara.agent import AgentManager
from clara.portal_contract import ContractViolation
from clara.portal_intake import PortalIntake, task_prompt
from clara.portal_outputs import closeout_reservations
from clara.portal_inputs import PortalInputs
from clara.portal_transport import PortalReply, PortalTransport, PortalUnavailable
from clara.workflows import Workflows
from test_portal_delivery import BASE, WORKER, setup, handler_for, wire


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


def test_general_information_request_needs_no_closeout_review_workflow(tmp_path):
    config, store, claim, _ = setup(tmp_path)
    claim.update(kind='general', closeout=None, required_outputs=[])
    claim['scope']['closeout_form_id'] = None
    claim['scope']['permissions'] = ['general']
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler_for(claim, []))) as client:
            transport = PortalTransport(BASE, lambda: 'test', client=client, clock=lambda: 100)
            manager = AgentManager(config, store)
            manager.reserve_execution('portal')
            prepared = await PortalIntake(config, store, manager, transport, WORKER).start_claim(
                PortalReply(claim, 100), reservation_id='portal')
            job = store.job(prepared.local_job_id)
            assert Workflows(store, config).get(job['conversation_id']) is None
            with pytest.raises(ValueError, match='information requests'):
                Workflows(store, config).begin(job, 't1-closeout', {'client_key':'x','year':'2024','members':['x']})
            assert manager.queue.get_nowait() == job['id']
    asyncio.run(scenario())


def test_all_source_files_must_arrive_before_acknowledgement_and_dispatch(tmp_path, monkeypatch):
    config, store, claim, _ = setup(tmp_path)
    claim['closeout']['attachments'] = [
        {'attachment_id':'88888888-8888-4888-8888-888888888888','name':'Slips.pdf'},
        {'attachment_id':'99999999-9999-4999-8999-999999999999','name':'Checklist.pdf'},
    ]
    calls, downloaded = [], []
    available = False
    async def scenario():
        nonlocal available
        def api(request):
            if request.url.path.endswith('/clara-attachment'):
                body = json.loads(request.content)
                item = next(a for a in claim['closeout']['attachments'] if a['attachment_id'] == body['attachment_id'])
                return wire({**item, 'download_url':BASE.replace('/functions/v1','') +
                    '/storage/v1/object/sign/documents/' + item['attachment_id'] + '?token=temporary',
                    'expires_at':'2026-09-14T00:05:00Z','server_time':'2026-09-14T00:00:00Z'})
            return handler_for(claim, calls)(request)
        def download(request):
            name = request.url.path.rsplit('/', 1)[-1]
            downloaded.append(name)
            if name.startswith('9999') and not available:
                return httpx.Response(503)
            return httpx.Response(200, content=b'%PDF-1.7\n' + name.encode())
        async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as client, \
                httpx.AsyncClient(transport=httpx.MockTransport(download)) as blobs:
            monkeypatch.setattr('clara.portal_intake.PortalInputs',
                lambda cfg, db, transport: PortalInputs(cfg, db, transport, client=blobs))
            transport = PortalTransport(BASE, lambda:'test', client=client, clock=lambda:100)
            manager = AgentManager(config, store)
            assert manager.reserve_execution('portal')
            intake = PortalIntake(config, store, manager, transport, WORKER)
            with pytest.raises(PortalUnavailable):
                await intake.start_claim(PortalReply(claim, 100), reservation_id='portal')
            assert manager.queue.empty() and store.rows('SELECT id FROM jobs') == []
            assert len(store.rows('SELECT * FROM portal_v1_inputs')) == 1
            assert all(name != 'clara-message-ack' for name, _ in calls)
            available = True
            prepared = await intake.start_claim(PortalReply(claim, 100), reservation_id='portal')
            assert manager.queue.get_nowait() == prepared.local_job_id
            assert calls[-1][0] == 'clara-message-ack'
            assert downloaded.count(claim['closeout']['attachments'][0]['attachment_id']) == 1
            assert len(store.rows('SELECT * FROM portal_v1_inputs')) == 2
            prompt = store.job(prepared.local_job_id)['prompt']
            assert 'Slips.pdf' in prompt and 'Checklist.pdf' in prompt
    asyncio.run(scenario())


def test_task_prompt_names_the_canonical_reservation_keys(tmp_path):
    config, store, claim, _ = setup(tmp_path)
    prompt, context = task_prompt(claim, [])
    form = claim['closeout']['closeout_form_id']
    assert f'pandadoc create_signature_packet closeout:{form}:pandadoc:m1' in prompt
    assert f'storage create_folder closeout:{form}:storage:folder' in prompt
    assert all(' '.join(t) in prompt for t in closeout_reservations(claim)) and context['client_key'] == form
    assert ('record_portal_delivery identities: member_id is one of m1; document_type is one of client_copy, '
            't183, engagement_letter; tax_year is ' + str(claim['closeout']['tax_year']) + '.') in prompt
    general = {**claim, 'kind':'general', 'closeout':None, 'required_outputs':[]}
    assert 'reserve_external_write' not in task_prompt(general, [])[0]


def test_task_prompt_requires_delivery_to_be_recorded_by_the_attempt_that_hands_off(tmp_path):
    config, store, claim, _ = setup(tmp_path)
    first, _ = task_prompt({**claim, 'attempt_no': 1}, [])
    assert 'call record_portal_delivery in this attempt even if an earlier attempt recorded delivery' in first
    assert 'This is attempt' not in first
    third, _ = task_prompt({**claim, 'attempt_no': 3}, [])
    assert ('This is attempt 3 of this closeout: before finishing, read the folder, its files and each packet '
            'again in Chrome and record delivery again.') in third
