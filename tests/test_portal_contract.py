import pytest

from clara.portal_contract import ContractViolation, PortalContract


def contract_fixture():
    return {
        '$schema': 'https://json-schema.org/draft/2020-12/schema',
        '$id': 'urn:clara:test-contract',
        'version': '1',
        '$defs': {'identity': {'type': 'object', 'required': ['job_id', 'fence_token'],
                              'properties': {'job_id': {'type': 'string'},
                                             'fence_token': {'type': 'integer', 'minimum': 1,
                                                             'maximum': 9007199254740991}},
                              'additionalProperties': False}},
        'operations': {'clara-heartbeat': {
            'request': {'$ref': '#/$defs/identity'},
            'response': {'type': 'object', 'required': ['server_time'],
                         'properties': {'server_time': {'type': 'string', 'format': 'date-time'}},
                         'additionalProperties': False}}},
    }


def test_uses_local_definitions_and_validates_both_directions():
    contract = PortalContract(contract_fixture())
    valid = {'job_id': 'a-job', 'fence_token': 1}
    assert contract.validate('clara-heartbeat', 'request', valid) == valid
    contract.validate('clara-heartbeat', 'response', {'server_time': '2026-09-14T13:00:00Z'})
    for payload in ({'job_id': 'a-job'}, {**valid, 'fence_token': True},
                    {**valid, 'fence_token': 9007199254740992}, {**valid, 'unexpected': 'field'}):
        with pytest.raises(ContractViolation):
            contract.validate('clara-heartbeat', 'request', payload)
    with pytest.raises(ContractViolation):
        contract.validate('clara-heartbeat', 'response', {'server_time': '2026-02-30T13:00:00Z'})


def test_wire_content_cannot_replace_schema_or_leak_through_diagnostics():
    document = contract_fixture()
    contract = PortalContract(document)
    document['$defs']['identity']['additionalProperties'] = True
    secret = 'private-client-value'
    with pytest.raises(ContractViolation) as caught:
        contract.validate('clara-heartbeat', 'request', {'job_id': 'a-job', 'fence_token': 1, 'token': secret})
    assert secret not in str(caught.value)
    with pytest.raises(ContractViolation):
        contract.validate('clara-unknown', 'request', {})


def test_contract_cannot_resolve_external_schemas():
    document = contract_fixture()
    document['operations']['clara-heartbeat']['request'] = {'$ref': 'https://example.invalid/schema.json'}
    with pytest.raises(ContractViolation, match='local references'):
        PortalContract(document)
    document = contract_fixture()
    document['operations']['clara-heartbeat']['request'] = {'$ref': '#/$defs/missing'}
    contract = PortalContract(document)
    with pytest.raises(ContractViolation):
        contract.validate('clara-heartbeat', 'request', {})


def test_unknown_version_and_metadata_only_export_fail_before_execution():
    document = contract_fixture()
    document['version'] = 'next'
    with pytest.raises(ContractViolation):
        PortalContract(document)
    document = contract_fixture()
    document['operations']['clara-heartbeat'] = {'audience': 'worker'}
    with pytest.raises(ContractViolation, match='missing its wire schema'):
        PortalContract(document)
