import asyncio
import json

import httpx
import pytest

from clara.agent import AgentManager
from clara.portal_bindings import PortalBindings
from clara.portal_journal import PortalJournal
from clara.portal_progress import PortalProgress
from clara.portal_quiescence import observe_quiescence
from clara.portal_transport import PortalTransport, PortalUnavailable
from test_portal_delivery import BASE, WORKER, CONTRACT, setup, wire


def test_progress_retries_same_chat_without_crossing_task_or_leaking_arguments(tmp_path):
    config, store, claim, lease = setup(tmp_path)
    jid = PortalBindings(store, BASE, WORKER).persist_claim(claim, 'Assigned task')['local_job_id']
    cid = store.job(jid)['conversation_id']
    other = store.create_conversation()
    store.event(other['id'], None, 'assistant', {'text': 'Another staff member private text'})
    store.event(cid, jid, 'tool', {'id': 't1', 'name': 'mcp__windows__PowerShell', 'input': 'private command'})
    store.event(cid, jid, 'assistant', {'text': 'Found the file.\n\nReady for the next step.'})
    calls = []
    def handle(request):
        body = json.loads(request.content)
        calls.append((request.url.path.rsplit('/', 1)[-1], body))
        if request.url.path.endswith('clara-chat'):
            if len([c for c in calls if c[0] == 'clara-chat']) == 1:
                raise httpx.ReadError('lost response', request=request)
            return wire(CONTRACT.document['fixtures']['clara-chat']['response'])
        uid = body['events'][0]['event_uid']
        return wire({**CONTRACT.document['fixtures']['clara-events']['response'], 'accepted_uids': [uid]})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            transport = PortalTransport(BASE, lambda: 'test', client=client)
            progress = PortalProgress(store, transport, PortalJournal(store, BASE), lease, jid)
            with pytest.raises(PortalUnavailable):
                await progress.flush()
            reopened = type(store)(store.path)
            progress = PortalProgress(reopened, transport, PortalJournal(reopened, BASE), lease, jid)
            await progress.flush()
            assert await progress.flush() == 0
    asyncio.run(scenario())
    chats = [b for op,b in calls if op == 'clara-chat']
    assert len(chats) == 2 and chats[0] == chats[1]
    assert chats[0]['body'] == 'Found the file.\n\nReady for the next step.'
    assert 'private' not in json.dumps(calls)
    assert len([c for c in calls if c[0] == 'clara-events']) == 1


def test_quiescence_keeps_unknown_tool_and_external_effects_held(tmp_path):
    config, store, claim, lease = setup(tmp_path)
    jid = PortalBindings(store, BASE, WORKER).persist_claim(claim, 'Assigned task')['local_job_id']
    cid = store.job(jid)['conversation_id']
    manager = AgentManager(config, store)
    store.status(jid, 'interrupted')
    store.event(cid, jid, 'tool', {'id': 'printing', 'name': 'mcp__windows__Click'})
    report = observe_quiescence(store, manager, BASE, lease.identity, jid)
    assert report['complete'] is False
    assert 'tool:printing' in report['unknown']
    store.event(cid, jid, 'tool_done', {'id': 'printing', 'name': 'mcp__windows__Click', 'failed': False})
    report = observe_quiescence(store, manager, BASE, lease.identity, jid)
    assert 'tool:printing' in report['finished']
    assert 'tool:printing' not in report['unknown']
    assert 'external-desktop-state-unconfirmed' in report['unknown']
    assert report['complete'] is False


def test_quiescence_never_reports_idle_while_waiting_or_truncates_unknowns(tmp_path):
    config, store, claim, lease = setup(tmp_path)
    jid = PortalBindings(store, BASE, WORKER).persist_claim(claim, 'Assigned task')['local_job_id']
    cid = store.job(jid)['conversation_id']
    manager = AgentManager(config, store)
    manager.active_job = jid
    report = observe_quiescence(store, manager, BASE, lease.identity, jid)
    assert report['in_flight'] == ['local-executor'] and report['complete'] is False
    manager.active_job = None
    store.status(jid, 'completed')
    assert observe_quiescence(store, manager, BASE, lease.identity, jid)['complete'] is True
    for i in range(201):
        store.event(cid, jid, 'tool', {'id': str(i), 'name': 'Read'})
    with pytest.raises(ValueError, match='retain the worker hold'):
        observe_quiescence(store, manager, BASE, lease.identity, jid)


def test_claras_command_tool_return_does_not_prove_its_external_actions_stopped(tmp_path):
    config, store, claim, lease = setup(tmp_path)
    jid = PortalBindings(store, BASE, WORKER).persist_claim(claim, 'Assigned task')['local_job_id']
    cid = store.job(jid)['conversation_id']
    manager = AgentManager(config, store)
    store.status(jid, 'completed')
    for kind in ('tool', 'tool_done'):
        store.event(cid, jid, kind, {'id':'shell', 'name':'mcp__clara__run_command'})
    report = observe_quiescence(store, manager, BASE, lease.identity, jid)
    assert report['complete'] is False
    assert 'external-desktop-state-unconfirmed' in report['unknown']
