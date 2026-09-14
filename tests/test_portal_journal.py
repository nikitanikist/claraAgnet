from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace

import pytest

from clara.portal_journal import JournalConflict, PortalJournal
from clara.portal_lease import AttemptIdentity
from clara.store import Store


IDENTITY = AttemptIdentity('portal-job', 'worker-one', 1, 7)


def stage(journal, *, identity=IDENTITY, outcome='needs_review'):
    return journal.stage(identity, 'clara-result', 'result-1',
                         {**asdict(identity), 'outcome': outcome})


def test_lost_response_and_restart_preserve_original_report_without_creating_work(tmp_path):
    path = tmp_path / 'clara.sqlite3'
    store = Store(path)
    original = stage(PortalJournal(store, 'portal-one'))
    # Simulate sending successfully but losing the response, then restarting.
    reopened = Store(path)
    reopened.recover()
    journal = PortalJournal(reopened, 'portal-one')
    assert journal.pending()[0]['payload'] == original['payload']
    assert stage(journal)['id'] == original['id']
    assert reopened.rows('SELECT * FROM jobs') == []
    receipt = {'receipt_id': 'original-server-receipt', 'result_recorded': True}
    journal.acknowledge(original['id'], receipt)
    assert PortalJournal(Store(path), 'portal-one').pending() == []
    assert stage(journal)['receipt'] == receipt


def test_changed_result_or_receipt_cannot_replace_durable_fact(tmp_path):
    journal = PortalJournal(Store(tmp_path / 'db'), 'portal-one')
    row = stage(journal)
    with pytest.raises(JournalConflict):
        stage(journal, outcome='completed_prepared')
    journal.acknowledge(row['id'], {'receipt_id': 'one'})
    with pytest.raises(JournalConflict):
        journal.acknowledge(row['id'], {'receipt_id': 'different'})
    assert journal.acknowledge(row['id'], {'receipt_id': 'one'})['receipt']['receipt_id'] == 'one'


def test_portal_and_attempt_boundaries_prevent_cross_acknowledgement(tmp_path):
    store = Store(tmp_path / 'db')
    first = PortalJournal(store, 'portal-one')
    second = PortalJournal(store, 'portal-two')
    row = stage(first)
    other = stage(second)
    next_identity = replace(IDENTITY, attempt_no=2, fence_token=8)
    next_row = stage(first, identity=next_identity)
    assert len({row['id'], other['id'], next_row['id']}) == 3
    with pytest.raises(JournalConflict):
        second.acknowledge(row['id'], {'receipt_id': 'wrong-portal'})
    assert [r['id'] for r in first.pending(IDENTITY)] == [row['id']]
    assert [r['id'] for r in first.pending(next_identity)] == [next_row['id']]


def test_concurrent_delivery_stages_one_logical_report(tmp_path):
    journal = PortalJournal(Store(tmp_path / 'db'), 'portal-one')
    with ThreadPoolExecutor(max_workers=4) as executor:
        rows = list(executor.map(lambda _: stage(journal), range(12)))
    assert len({r['id'] for r in rows}) == 1
    assert len(journal.pending()) == 1


def test_rejects_mismatched_payload_before_persistence(tmp_path):
    journal = PortalJournal(Store(tmp_path / 'db'), 'portal-one')
    for key, changed in [('job_id', 'other'), ('worker_id', 'other'),
                         ('attempt_no', True), ('fence_token', 8)]:
        with pytest.raises(JournalConflict):
            journal.stage(IDENTITY, 'clara-result', 'one', {**asdict(IDENTITY), key: changed})
    with pytest.raises(ValueError):
        journal.stage(IDENTITY, 'clara-result', 'one', {**asdict(IDENTITY), 'cost': float('nan')})
    assert journal.pending() == []
