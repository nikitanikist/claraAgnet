import copy
import json

import pytest

from clara.portal_bindings import PortalBindings, SOFTWARE_PERMISSIONS
from clara.portal_contract import ContractViolation
from clara.portal_documents import collect_documents
from clara.portal_intake import task_prompt
from clara.portal_windows import WindowsHandoff
from clara.workflows import Workflows
from test_core import make_pdf
from test_portal_delivery import BASE, WORKER, setup
from test_portal_documents import package
from test_portal_windows import task


def profile_claim(claim):
    later = copy.deepcopy(claim)
    later['closeout']['software'] = 'profile'
    later['closeout']['file_path'] = r'O:\Clearhouse Clara agent\Profile files\Anderson, Patrick.25T'
    later['scope']['permissions'] = ['closeout.t1.profile']
    return later


def test_a_profile_closeout_is_accepted_only_with_its_own_permission(tmp_path):
    config, store, claim, _ = setup(tmp_path)
    bindings = PortalBindings(store, BASE, WORKER)
    row = bindings.persist_claim(profile_claim(claim), 'Prepare this ProFile T1')
    assert json.loads(row['claim_json'])['closeout']['software'] == 'profile'
    wrong = profile_claim(claim)
    wrong['scope']['permissions'] = ['closeout.t1.taxprep']   # the TaxPrep grant does not cover ProFile
    wrong['job_id'] = '11111111-1111-4111-8111-111111111112'
    with pytest.raises(ContractViolation, match='TaxPrep and ProFile'):
        bindings.persist_claim(wrong, 'Prepare')
    unknown = profile_claim(claim)
    unknown['closeout']['software'] = 'cantax'
    unknown['job_id'] = '11111111-1111-4111-8111-111111111113'
    with pytest.raises(ContractViolation):
        bindings.persist_claim(unknown, 'Prepare')
    assert SOFTWARE_PERMISSIONS == {'taxprep': 'closeout.t1.taxprep', 'profile': 'closeout.t1.profile'}


def test_the_task_prompt_names_the_skill_for_each_application(tmp_path):
    config, store, claim, _ = setup(tmp_path)
    taxprep, _ = task_prompt(claim, [])
    profile, _ = task_prompt(profile_claim(claim), [])
    for prompt in (taxprep, profile):
        assert 'load taxprep-fast-path' in prompt and 'load profile-fast-path' in prompt
        assert 'ProFile, T2 and T3 execution are unavailable' not in prompt
        assert 'T2 and T3 execution are unavailable' in prompt
        assert 'never change Options or press Enter in Form Selection' in prompt
    assert '"software": "profile"' in profile and '.25T' in profile


def test_a_prepared_profile_closeout_counts_for_automatic_release(tmp_path):
    config, store, claim, lease = setup(tmp_path)
    claim = profile_claim(claim)
    from clara.portal_journal import PortalJournal
    from dataclasses import asdict
    jid = PortalBindings(store, BASE, WORKER).persist_claim(claim, 'Prepare this ProFile T1')['local_job_id']
    store.status(jid, 'needs_review')
    journal = PortalJournal(store, BASE)
    row = journal.stage(lease.identity, 'clara-result', 'result-' + jid, {**asdict(lease.identity), 'outcome': 'completed_prepared'})
    journal.acknowledge(row['id'], {'accepted': True})
    assert WindowsHandoff(store).prepared_closeout(jid) is True


def test_instalments_and_t1135_are_delivered_when_verified_but_never_required(tmp_path):
    config, store, job, lease, proofs = package(tmp_path)
    wf = Workflows(store, config)
    context = wf.get(job['conversation_id'])['context']
    person, year = context['members'][0], context['year']
    extra = config.workspace / 'instalments.pdf'
    make_pdf(extra, f'{person} {int(year) + 1} Instalments payment schedule')
    optional = wf.verify_document(job, str(extra), person, 'instalments', year)['id']
    documents = collect_documents(config, store, BASE, lease.identity, job['id'], proofs + [optional])
    assert {d.document_type for d in documents} == {'client_copy', 't183', 'engagement_letter', 'instalments'}
    assert collect_documents(config, store, BASE, lease.identity, job['id'], proofs) and True, 'optional forms stay optional'
    with pytest.raises(ContractViolation, match='all required PDFs'):
        collect_documents(config, store, BASE, lease.identity, job['id'], proofs[:-1] + [optional])
    with pytest.raises(ValueError):
        wf.verify_document(job, str(extra), person, 'schedule-9', year)  # not a delivered output type
