import pytest

from clara.portal_bindings import PortalBindings
from clara.portal_contract import ContractViolation
from clara.portal_documents import collect_documents
from clara.workflows import Workflows
from test_core import make_pdf
from test_portal_delivery import BASE, WORKER, setup


def package(tmp_path):
    config, store, claim, lease = setup(tmp_path)
    row = PortalBindings(store, BASE, WORKER).persist_claim(claim, 'Prepare assigned family')
    job = store.job(row['local_job_id'])
    wf = Workflows(store, config)
    person = claim['closeout']['members'][0]['member_name']
    year = claim['closeout']['tax_year']
    wf.begin(job, 't1-closeout', {'client_key': claim['closeout']['closeout_form_id'], 'year': year, 'members': [person]})
    proofs = []
    for kind in ['client-copy', 't183', 'engagement-letter']:
        path = config.workspace / (kind + '.pdf')
        make_pdf(path, f'{person} {year} income tax T183 engagement {kind}')
        proofs.append(wf.verify_document(job, str(path), person, kind, year)['id'])
    return config, store, job, lease, proofs


def test_document_manifest_uses_exact_ids_types_and_reuses_published_snapshots(tmp_path):
    config, store, job, lease, proofs = package(tmp_path)
    first = collect_documents(config, store, BASE, lease.identity, job['id'], proofs)
    second = collect_documents(config, store, BASE, lease.identity, job['id'], proofs)
    assert [d.file.file_id for d in first] == [d.file.file_id for d in second]
    assert len(store.rows("SELECT id FROM files WHERE kind='artifact'")) == 3
    assert {d.document_type for d in first} == {'client_copy', 't183', 'engagement_letter'}
    assert {d.member_id for d in first} == {'m1'}
    for d in first:
        fields = d.allocation_fields()
        assert fields['tax_year'] == '2024' and fields['bytes'] == len(d.file.data)
        assert fields['sha256'] == d.file.sha256


def test_missing_or_changed_document_never_becomes_a_ready_manifest(tmp_path):
    config, store, job, lease, proofs = package(tmp_path)
    with pytest.raises(ContractViolation, match='all required PDFs'):
        collect_documents(config, store, BASE, lease.identity, job['id'], proofs[:-1])
    assert store.rows('SELECT id FROM files') == []
    make_pdf(config.workspace / 'client-copy.pdf', 'Wrong person 2025')
    with pytest.raises(ValueError, match='changed'):
        collect_documents(config, store, BASE, lease.identity, job['id'], proofs)
    assert store.rows('SELECT id FROM files') == []
