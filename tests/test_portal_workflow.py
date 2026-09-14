import copy
import asyncio
import json
from uuid import uuid4

import pytest

from clara.config import Config
from clara.agent import AgentManager
from clara.portal_bindings import PortalBindings
from clara.portal_contract import PortalContract
from clara.store import Store
from clara.workflows import Workflows


@pytest.fixture
def portal_task(tmp_path):
    config = Config(tmp_path / 'data')
    config.initialize()
    store = Store(config.data / 'db')
    claim = copy.deepcopy(PortalContract.bundled().document['fixtures']['clara-claim']['response'])
    binding = PortalBindings(store, 'https://example.supabase.co/functions/v1',
                             '22222222-2222-4222-8222-222222222222').persist_claim(claim, 'Prepare assigned T1.')
    context = {'client_key': claim['closeout']['closeout_form_id'],
               'year': claim['closeout']['tax_year'],
               'members': [m['member_name'] for m in claim['closeout']['members']]}
    return store, store.job(binding['local_job_id']), Workflows(store, config), context


def test_portal_preparation_keeps_documents_and_review_but_invoice_is_manual(portal_task):
    store, job, workflows, context = portal_task
    result = workflows.begin(job, 't1-closeout', context, {'documents': []})
    assert 'invoice' not in result['contract']
    assert result['contract']['delivery'] == [{'kind': 'remote_record', 'system': 'storage'}]
    assert len(result['contract']['documents']) == 3
    assert result['contract']['source-copy'] and result['contract']['application']
    assert result['context']['invoice_responsibility'] == 'laureen_manual'
    assert 'review' in result['contract']
    assert workflows.finish_check(job).startswith('Workflow incomplete')
    with pytest.raises(ValueError):
        workflows.review(job['conversation_id'], 'Looks ready')


def test_model_cannot_change_the_assigned_client_year_or_tax_workflow(portal_task):
    store, job, workflows, context = portal_task
    for changed in ({**context, 'client_key': 'another-client'}, {**context, 'year': '2030'},
                    {**context, 'members': ['Somebody Else']}):
        with pytest.raises(ValueError):
            workflows.begin(job, 't1-closeout', changed)
    with pytest.raises(ValueError):
        workflows.begin(job, 't1-print', context)
    with pytest.raises(ValueError):
        workflows.begin(job, 't2-preparation', context)
    assert workflows.get(job['conversation_id']) is None


def test_unbound_model_flag_cannot_remove_original_closeout_obligations(portal_task):
    store, _, workflows, context = portal_task
    conversation = store.create_conversation()
    job = store.create_job(conversation['id'], 'Other closeout', 'autonomous', [])
    result = workflows.begin(job, 't1-closeout', {**context, 'invoice_responsibility': 'laureen_manual',
                                                'handoff_responsibility': 'portal_after_result'})
    assert result['contract']['invoice'] == [{'kind': 'remote_record', 'system': 'billing'}]
    assert {'kind': 'remote_record', 'system': 'portal'} in result['contract']['delivery']


@pytest.mark.parametrize('decision,changed', [('Continue with incomplete usage', False), ('Keep paused', False),
                                            ('Continue with incomplete usage', True)])
def test_portal_continuation_reviews_missing_usage_in_chat_without_changing_costs_or_limits(portal_task, decision, changed):
    store, previous, workflows, context = portal_task
    workflows.begin(previous, 't1-closeout', context)
    store.status(previous['id'], 'interrupted')
    row = store.one('SELECT * FROM portal_v1_attempts WHERE local_job_id=?', (previous['id'],))
    claim = copy.deepcopy(PortalContract.bundled().document['fixtures']['clara-claim']['response'])
    claim.update(json.loads(row['claim_json']))
    claim.update(attempt_no=claim['attempt_no'] + 1, fence_token=claim['fence_token'] + 1, execution_id=str(uuid4()))
    binding = PortalBindings(store, row['namespace'], row['worker_id']).persist_claim(claim, 'Continue the existing task.')
    job = store.job(binding['local_job_id'])
    workflows.attach(job)
    original_limits = workflows.get(job['conversation_id'])['limits']
    manager = AgentManager(workflows.config, store)
    questions = []
    async def answer(asked_job, kind, data):
        from clara.portal_control import question_payload
        wire = question_payload(kind, data)
        assert asked_job['id'] == job['id']
        assert wire['question'] == 'Continue with incomplete usage information?'
        assert wire['choices'] == ['Continue', 'Keep paused']
        questions.append(wire)
        if changed:
            store.status(previous['id'], 'failed')
        return decision
    manager.request_input = answer
    async def scenario():
        if decision == 'Keep paused' or changed:
            with pytest.raises(ValueError, match='paused|history changed'):
                await manager._workflow_budget(job, workflows)
            assert workflows.remaining(job['conversation_id'])['requires_usage_review']
        else:
            result = await manager._workflow_budget(job, workflows)
            assert result['partial'] and not result['requires_usage_review']
            # An unchanged reviewed snapshot is not asked about again.
            await manager._workflow_budget(job, workflows)
        assert len(questions) == 1
        assert store.job(previous['id'])['usage'] is None
        assert workflows.get(job['conversation_id'])['limits'] == original_limits
        assert manager.queue.empty()
    asyncio.run(scenario())
