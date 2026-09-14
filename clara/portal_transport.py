"""One-attempt HTTPS transport for the reviewed ClearForm Hub worker protocol.

No model or desktop work starts here. Ambiguous network outcomes stay ambiguous:
only durable, idempotent reports can be retried using their original payload.
The configured worker key is sent only to the configured functions origin.
"""
from dataclasses import dataclass
import json
import time
from urllib.parse import urlsplit, urlunsplit

import httpx

from .portal_contract import ContractViolation, PortalContract
from .portal_journal import JournalConflict


ERROR_CODES = frozenset({
    'unsupported_contract', 'unauthorized', 'forbidden', 'not_found',
    'invalid_request', 'idempotency_conflict', 'fenced', 'lease_expired',
    'active_job_exists', 'resource_locked', 'unsupported_workflow',
    'execution_disabled', 'invalid_state', 'answer_expired',
    'artifact_unverified', 'snapshot_stale', 'incomplete_outputs',
    'invoice_policy_unset', 'finalization_in_progress', 'internal_error',
})
REPORT_OPERATIONS = frozenset({
    'clara-result', 'clara-quiesce', 'clara-events', 'clara-chat',
    'clara-ask', 'clara-command-ack',
})
MAX_RESPONSE_BYTES = 1_048_576


class PortalUnavailable(RuntimeError):
    """No validated receipt was obtained; this does not mean nothing happened."""


class PortalRejected(RuntimeError):
    def __init__(self, code, status):
        self.code, self.status = code, status
        # Never expose server message text: it may include client data or URLs.
        super().__init__(f'Portal rejected the request ({code}; HTTP {status}).')


@dataclass(frozen=True)
class PortalReply:
    body: dict
    request_started: float


def functions_base_url(value):
    if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError('Configure a valid HTTPS portal functions URL.')
    try:
        u = urlsplit(value)
        if (u.scheme != 'https' or not u.hostname or u.username or u.password
                or u.query or u.fragment or u.path.rstrip('/') != '/functions/v1'
                or u.port not in (None, 443)):
            raise ValueError()
    except ValueError:
        raise ValueError('Configure an HTTPS portal URL ending in /functions/v1.') from None
    return urlunsplit(('https', u.netloc.lower(), '/functions/v1', '', ''))


class PortalTransport:
    def __init__(self, base_url, key_provider, *, contract=None, client=None, clock=time.monotonic):
        self.base_url = functions_base_url(base_url)
        if not callable(key_provider):
            raise ValueError('Supply the configured worker credential provider.')
        self.key_provider = key_provider
        self.contract = contract or PortalContract.bundled()
        self.clock = clock
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False)

    async def close(self):
        if self._owns_client:
            await self.client.aclose()

    def _request_snapshot(self, operation, payload):
        op = self.contract.document['operations'].get(operation)
        if not op or op.get('audience') != 'worker':
            raise ContractViolation('This connection only supports worker operations.')
        self.contract.validate(operation, 'request', payload)
        return json.loads(json.dumps(payload, allow_nan=False))

    async def request(self, operation, payload, *, request_key=None):
        body = self._request_snapshot(operation, payload)
        key = self.key_provider()
        if (not isinstance(key, str) or not key or len(key) > 4096
                or any(ord(c) < 33 or ord(c) > 126 for c in key)):
            raise ValueError('The configured portal worker credential is unavailable.')
        headers = {'x-clara-contract': '1', 'x-clara-worker-key': key,
                   'content-type': 'application/json', 'accept': 'application/json'}
        if request_key is not None:
            if (not isinstance(request_key, str) or not request_key or len(request_key) > 200
                    or any(ord(c) < 33 or ord(c) > 126 for c in request_key)):
                raise ValueError('A report needs a valid idempotency key.')
            headers['idempotency-key'] = request_key
        started = self.clock()
        try:
            # Explicit no-redirect applies even if an injected client defaults to
            # following redirects. A 3xx must never forward a worker credential.
            async with self.client.stream('POST', self.base_url + '/' + operation,
                                          headers=headers, json=body, follow_redirects=False) as response:
                if (response.headers.get('x-clara-contract') != '1'
                        or response.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json'):
                    raise PortalUnavailable('The portal returned no compatible response.')
                if 300 <= response.status_code < 400:
                    raise PortalUnavailable('The portal redirected the worker request.')
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_RESPONSE_BYTES:
                        raise PortalUnavailable('The portal response exceeds the protocol limit.')
                try:
                    result = json.loads(content)
                except (ValueError, UnicodeError):
                    raise PortalUnavailable('The portal returned an invalid response.') from None
                if response.status_code < 200 or response.status_code >= 300:
                    self.contract.validate('error', 'response', result)
                    code = result.get('error')
                    if code not in ERROR_CODES:
                        raise PortalUnavailable('The portal returned an unknown error code.')
                    raise PortalRejected(code, response.status_code)
                self.contract.validate(operation, 'response', result)
                return PortalReply(result, started)
        except (httpx.HTTPError, OSError):
            # HTTP exceptions include request URLs and possibly response bodies.
            raise PortalUnavailable('No portal receipt was obtained; preserve the existing attempt.') from None

    async def report(self, journal, identity, operation, request_key, payload):
        if operation not in REPORT_OPERATIONS:
            raise ValueError('Only idempotent reports belong in the report journal.')
        if journal.namespace != self.base_url:
            raise JournalConflict('This report belongs to another portal connection.')
        body = self._request_snapshot(operation, payload)
        if operation == 'clara-result' and body['idempotency_key'] != request_key:
            raise JournalConflict('The result key must match its durable request key.')
        row = journal.stage(identity, operation, request_key, body)
        if row['receipt'] is not None:
            self._check_receipt(operation, body, row['receipt'])
            return row['receipt']
        reply = await self.request(operation, row['payload'], request_key=request_key)
        self._check_receipt(operation, body, reply.body)
        journal.acknowledge(row['id'], reply.body)
        return reply.body

    def _check_receipt(self, operation, body, receipt):
        self.contract.validate(operation, 'response', receipt)
        if operation == 'clara-result' and (receipt['accepted'] is not True or receipt['result_recorded'] is not True):
            raise PortalUnavailable('The portal has not confirmed recording this result.')
        if operation == 'clara-command-ack' and (receipt['command_id'] != body['command_id'] or not receipt['recorded']):
            raise PortalUnavailable('The portal has not acknowledged this command.')
        if operation == 'clara-ask' and receipt['request_id'] != body['request_id']:
            raise PortalUnavailable('The portal replied to a different question.')
        if operation == 'clara-events':
            expected = {event['event_uid'] for event in body['events']}
            actual = set(receipt['accepted_uids']) | set(receipt['duplicate_uids'])
            if actual != expected:
                raise PortalUnavailable('The portal has not acknowledged every event.')
