import copy
from concurrent.futures import ThreadPoolExecutor

import pytest

from clara.portal_bindings import BindingConflict, PortalBindings
from clara.portal_contract import ContractViolation, PortalContract
from clara.store import Store


BASE = 'https://example.supabase.co/functions/v1'
WORKER = '22222222-2222-4222-8222-222222222222'


def claim():
    return copy.deepcopy(PortalContract.bundled().document['fixtures']['clara-claim']['response'])


def test_claim_binding_is_atomic_and_restart_never_creates_another_job(tmp_path):
    path = tmp_path / 'db'
    store = Store(path)
    bindings = PortalBindings(store, BASE, WORKER)
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda _: bindings.persist_claim(claim(), 'Prepare this T1.'), range(8)))
    assert sum(r['created_now'] for r in rows) == 1
    assert len({r['local_job_id'] for r in rows}) == 1
    assert len(store.rows('SELECT * FROM jobs')) == 1
    reopened = Store(path)
    reopened.recover()
    existing = PortalBindings(reopened, BASE, WORKER).persist_claim(claim(), 'Resume?')
    assert existing['created_now'] is False
    job = reopened.job(existing['local_job_id'])
    assert job['status'] == 'interrupted'
    assert job['prompt'] == 'Prepare this T1.'


def test_continuation_reuses_conversation_but_has_distinct_attempt_and_job(tmp_path):
    store = Store(tmp_path / 'db')
    bindings = PortalBindings(store, BASE, WORKER)
    first = bindings.persist_claim(claim(), 'Prepare this T1.')
    store.status(first['local_job_id'], 'interrupted')
    next_claim = {**claim(), 'attempt_no': 4, 'fence_token': 92, 'execution_id': 'exec_92'}
    second = bindings.persist_claim(next_claim, 'Inspect saved work and continue.')
    assert first['local_job_id'] != second['local_job_id']
    assert store.job(first['local_job_id'])['conversation_id'] == store.job(second['local_job_id'])['conversation_id']
    assert len(store.rows('SELECT * FROM conversations')) == 1


def test_different_staff_chats_and_portals_never_share_local_sessions(tmp_path):
    store = Store(tmp_path / 'db')
    original = claim()
    original['kind'] = 'general'
    original['closeout'] = None
    original['scope']['closeout_form_id'] = None
    first = PortalBindings(store, BASE, WORKER).persist_claim(original, 'Find a client file.')
    store.status(first['local_job_id'], 'completed')
    local_cid = store.job(first['local_job_id'])['conversation_id']
    store.execute('UPDATE conversations SET session_id=? WHERE id=?', ('private-session', local_cid))
    changed_owner = copy.deepcopy(original)
    changed_owner.update(job_id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', execution_id='exec_93', fence_token=93)
    changed_owner['scope']['assigned_by'] = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
    with pytest.raises(BindingConflict):
        PortalBindings(store, BASE, WORKER).persist_claim(changed_owner, 'Different staff member.')
    changed_owner['conversation_id'] = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
    second = PortalBindings(store, BASE, WORKER).persist_claim(changed_owner, 'Another private conversation.')
    third = PortalBindings(store, 'https://other.supabase.co/functions/v1', WORKER).persist_claim(original, 'Other portal.')
    ids = [store.job(r['local_job_id'])['conversation_id'] for r in (first, second, third)]
    assert len(set(ids)) == 3
    assert [store.conversation(cid)['session_id'] for cid in ids] == ['private-session', None, None]


def test_conflicting_identity_or_scope_cannot_replace_existing_work(tmp_path):
    store = Store(tmp_path / 'db')
    bindings = PortalBindings(store, BASE, WORKER)
    first = bindings.persist_claim(claim(), 'Prepare this T1.')
    for change in ({'fence_token': 99}, {'execution_id': 'different'}, {'message_boundary_seq': 99}):
        with pytest.raises(BindingConflict):
            bindings.persist_claim({**claim(), **change}, 'Changed claim.')
    unsupported = claim()
    unsupported['closeout']['software'] = 'profile'
    with pytest.raises(ContractViolation):
        bindings.persist_claim(unsupported, 'ProFile task.')
    other = {**claim(), 'attempt_no': 4, 'fence_token': 92, 'execution_id': 'exec_92'}
    with pytest.raises(BindingConflict):
        bindings.persist_claim(other, 'Second task while first is still queued.')
    assert len(store.rows('SELECT * FROM jobs')) == 1
    assert store.job(first['local_job_id'])['prompt'] == 'Prepare this T1.'
