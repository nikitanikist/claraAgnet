"""Map verified local PDF evidence to the portal's exact family member IDs."""
from dataclasses import dataclass
import json
from pathlib import Path

from .portal_artifacts import PublishedFile, published_snapshot
from .portal_contract import ContractViolation
from .portal_progress import check_binding
from .tools import publish_artifact
from .workflows import Workflows


DOCUMENT_TYPES = {'client-copy': 'client_copy', 't183': 't183', 'engagement-letter': 'engagement_letter'}
# Forms a return may call for; delivered when verified, never required.
OPTIONAL_DOCUMENT_TYPES = {'instalments': 'instalments', 't1135': 't1135'}
ALL_DOCUMENT_TYPES = {**DOCUMENT_TYPES, **OPTIONAL_DOCUMENT_TYPES}


@dataclass(frozen=True)
class PortalDocument:
    member_id: str
    document_type: str
    tax_year: str
    evidence_id: str
    file: PublishedFile

    def allocation_fields(self):
        return {'file_name': self.file.name, 'content_type': self.file.content_type,
                'bytes': len(self.file.data), 'sha256': self.file.sha256,
                'member_id': self.member_id, 'document_type': self.document_type, 'tax_year': self.tax_year}


def collect_documents(config, store, namespace, identity, local_job_id, evidence_ids):
    binding = check_binding(store, namespace, identity, local_job_id)
    claim = json.loads(binding['claim_json'])
    if claim['kind'] != 'closeout':
        raise ContractViolation('Only an assigned closeout has a family document manifest.')
    closeout = claim['closeout']
    members = closeout['members']
    names = [m['member_name'] for m in members]
    if len({n.casefold() for n in names}) != len(names):
        raise ContractViolation('This family has ambiguous member names; verify member-specific evidence before uploading.')
    ids_by_name = {m['member_name']: m['member_id'] for m in members}
    if len(set(ids_by_name.values())) != len(members):
        raise ContractViolation('The assignment repeats a family member identity.')
    job = store.job(local_job_id)
    # These proofs are from this conversation and the current source hashes are
    # checked again. A file's name or a model assertion alone is insufficient.
    proofs = Workflows(store, config)._proofs(job, evidence_ids)
    chosen = {}
    for proof in proofs:
        if proof['kind'] != 'document':
            continue
        data = proof['payload']
        if (data.get('member') not in ids_by_name or data.get('document_type') not in ALL_DOCUMENT_TYPES
                or str(data.get('year')) != str(closeout['tax_year'])):
            raise ContractViolation('A document does not match this family, tax year or a delivered output type.')
        key = (ids_by_name[data['member']], ALL_DOCUMENT_TYPES[data['document_type']])
        if key in chosen and chosen[key]['payload']['sha256'] != data['sha256']:
            raise ContractViolation('Conflicting PDFs were supplied for the same family member and document type.')
        chosen[key] = proof
    expected = {(m['member_id'], doc) for m in members for doc in DOCUMENT_TYPES.values()}
    if not expected <= set(chosen):
        raise ContractViolation('Verify all required PDFs for every assigned family member before uploading the package.')
    if len({p['payload']['sha256'] for p in chosen.values()}) != len(chosen):
        raise ContractViolation('One PDF was used for multiple required outputs. Verify the separate member-specific documents.')

    documents = []
    for (member_id, document_type), proof in sorted(chosen.items()):
        data = proof['payload']
        name = Path(data['path']).name
        candidates = store.rows("SELECT id FROM files WHERE conversation_id=? AND kind='artifact' AND name=? ORDER BY created DESC",
                                (job['conversation_id'], name))
        snapshot = None
        for candidate in candidates:
            try:
                snapshot = published_snapshot(config, store, local_job_id, candidate['id'], expected_sha256=data['sha256'])
                break
            except ValueError:
                continue
        if snapshot is None:
            artifact = publish_artifact(config, store, job, data['path'])
            snapshot = published_snapshot(config, store, local_job_id, artifact['id'], expected_sha256=data['sha256'])
        if snapshot.content_type != 'application/pdf':
            raise ContractViolation('A verified tax document must be an actual PDF.')
        documents.append(PortalDocument(member_id, document_type, str(closeout['tax_year']), proof['id'], snapshot))
    return documents
