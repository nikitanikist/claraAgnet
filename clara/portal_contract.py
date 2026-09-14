"""Validate portal messages against a reviewed, self-contained JSON contract.

The adapter supplies its bundled contract. It never downloads a schema from a
server response, and schema references cannot retrieve network resources.
"""
import json
from importlib.resources import files

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012


class ContractViolation(ValueError):
    pass


class PortalContract:
    @classmethod
    def bundled(cls):
        return cls(json.loads(files('clara').joinpath('contracts/portal-v1.json').read_text()))

    def __init__(self, document):
        try:
            self.document = json.loads(json.dumps(document, allow_nan=False))
        except (TypeError, ValueError):
            raise ContractViolation('The bundled portal contract is not valid JSON.') from None
        doc = self.document
        if not isinstance(doc, dict) or doc.get('version') != '1':
            raise ContractViolation('Unsupported bundled portal contract version.')
        if doc.get('$schema') != 'https://json-schema.org/draft/2020-12/schema':
            raise ContractViolation('The portal contract must declare JSON Schema 2020-12.')
        operations = doc.get('operations')
        if not isinstance(operations, dict) or not operations:
            raise ContractViolation('The portal contract has no operations.')
        self._check_references(doc)
        try:
            Draft202012Validator.check_schema(doc)
            resource = Resource.from_contents(doc, default_specification=DRAFT202012)
            base = str(doc.get('$id') or 'urn:clara:portal-contract:1')
            registry = Registry().with_resource(base, resource)
            self.validators = {}
            if isinstance(doc.get('error'), dict):
                Draft202012Validator.check_schema(doc['error'])
                self.validators['error', 'response'] = Draft202012Validator(
                    {'$ref': f'{base}#/error'}, registry=registry, format_checker=FormatChecker())
            for name, operation in operations.items():
                if not isinstance(name, str) or not name.startswith('clara-') or len(name) > 80:
                    raise ContractViolation('The portal contract has an invalid operation name.')
                if not isinstance(operation, dict):
                    raise ContractViolation('The portal contract has an invalid operation.')
                pointer = name.replace('~', '~0').replace('/', '~1')
                for direction in ('request', 'response'):
                    schema = operation.get(direction)
                    if not isinstance(schema, dict):
                        raise ContractViolation('A portal operation is missing its wire schema.')
                    Draft202012Validator.check_schema(schema)
                    self.validators[name, direction] = Draft202012Validator(
                        {'$ref': f'{base}#/operations/{pointer}/{direction}'},
                        registry=registry, format_checker=FormatChecker())
        except SchemaError:
            raise ContractViolation('The bundled portal contract contains an invalid schema.') from None

    @staticmethod
    def _check_references(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ('$ref', '$dynamicRef') and isinstance(value, str) and not value.startswith('#'):
                    raise ContractViolation('Portal schemas must use local references only.')
                if key == 'format' and isinstance(value, str) and value not in FormatChecker.checkers:
                    raise ContractViolation('A required portal format validator is not installed.')
                PortalContract._check_references(value)
        elif isinstance(node, list):
            for item in node:
                PortalContract._check_references(item)

    def validate(self, operation, direction, payload):
        validator = self.validators.get((operation, direction))
        if validator is None:
            raise ContractViolation('Unknown portal operation or message direction.')
        try:
            if not isinstance(payload, dict) or len(json.dumps(payload, allow_nan=False).encode('utf-8')) > 1_048_576:
                raise ValueError()
            if not validator.is_valid(payload):
                raise ValueError()
        except Exception:
            # Validation errors can include passwords, signed links or client
            # content from the payload. Expose a fixed diagnostic instead.
            raise ContractViolation('Portal message does not match the reviewed contract.') from None
        return payload
