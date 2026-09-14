"""Observe a dedicated Windows session around one portal task.

Automatic handoff is deliberately limited to a clean, qualified dedicated
session after successful completion. Uncertain/interrupted work keeps the
existing portal reconciliation flow. Observations never authorize execution.
"""
import asyncio
import inspect
import json
import math
import os
import subprocess
import tempfile
import time
from pathlib import Path

from .auth import clean_environment
from .connectors import desktop_command

SHELL_CLASSES = {'Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd'}
CONSOLE_CLASSES = {'ConsoleWindowClass', 'CASCADIA_HOSTING_WINDOW_CLASS'}


async def native_snapshot():
    command = desktop_command()
    if os.name != 'nt' or not command:
        raise ValueError('Windows observation is unavailable.')
    with tempfile.TemporaryFile() as output:
        process = await asyncio.create_subprocess_exec(command[0], str(Path(__file__).with_name('windows_activity.py')),
            str(os.getpid()), env=clean_environment(), stdout=output, stderr=asyncio.subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            await asyncio.wait_for(process.wait(), 8)
        finally:
            if process.returncode is None:
                process.kill()  # Only this read-only probe, never an application.
                await process.wait()
        output.seek(0)
        data = output.read(1_000_001)
        if process.returncode or len(data) > 1_000_000:
            raise ValueError('Windows observation did not finish completely.')
        return json.loads(data)


def validate_snapshot(value):
    if not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 1 or value.get('errors') != []:
        raise ValueError('Windows observation is incomplete.')
    if value.get('interactive') is not True:
        raise ValueError('The dedicated Windows session is not active and unlocked.')
    for field in ('observed_at', 'boot'):
        if type(value.get(field)) not in {int, float} or not math.isfinite(value[field]):
            raise ValueError('Windows observation lacks a time identity.')
    if abs(time.time() - value['observed_at']) > 15:
        raise ValueError('Windows observation is stale.')
    if type(value.get('session')) is not int or value['session'] < 1:
        raise ValueError('Windows session identity is missing.')
    if not isinstance(value.get('controller'), list) or len(value['controller']) != 2:
        raise ValueError('Windows controller identity is missing.')
    if not isinstance(value.get('owner'), str) or len(value['owner']) != 64:
        raise ValueError('Windows account identity is missing.')
    for field in ('processes', 'windows', 'print_jobs', 'ancestors'):
        if not isinstance(value.get(field), list) or len(value[field]) > 10000:
            raise ValueError('Windows activity list is incomplete.')
    for process in value['processes']:
        if (type(process.get('pid')) is not int or process['pid'] < 1 or
                type(process.get('created')) not in {int, float} or not math.isfinite(process['created'])):
            raise ValueError('A Windows process lacks its creation identity.')
    return value


def process_key(row):
    return (row['pid'], row['created'])


def window_key(row):
    return (row['handle'], row['pid'], row['class'])


def baseline_issues(snapshot):
    issues = []
    # Console hosts are retained so the operator can keep Clara's startup
    # PowerShell open. Every other application window must start closed.
    if any(w['class'] not in SHELL_CLASSES | CONSOLE_CLASSES for w in snapshot['windows']):
        issues.append('windows-baseline-applications-open')
    if snapshot['print_jobs']:
        issues.append('windows-baseline-printing-active')
    # Hidden instances of task applications cannot silently become baseline
    # services; they could otherwise be reused without showing up as new PIDs.
    names = {'chrome.exe', 'msedge.exe', 't1txp.exe', 'profile.exe', 'winword.exe', 'excel.exe', 'acrord32.exe', 'acrobat.exe'}
    if any(p.get('name', '').casefold() in names for p in snapshot['processes']):
        issues.append('windows-baseline-task-application-running')
    return issues


class WindowsHandoff:
    def __init__(self, store, *, exclusive=False, qualified=False, probe=native_snapshot, clock=time.monotonic):
        self.store, self.exclusive, self.qualified = store, exclusive, qualified
        self.probe, self.clock = probe, clock
        self.clear_since = {}

    def prepared_closeout(self, jid):
        binding = self.store.one('SELECT * FROM portal_v1_attempts WHERE local_job_id=?', (jid,))
        if not binding:
            return False
        claim = json.loads(binding['claim_json'])
        if claim['kind'] != 'closeout' or 'closeout.t1.taxprep' not in claim['scope']['permissions']:
            return False
        result = self.store.one('''SELECT payload,receipt FROM portal_v1_outbox WHERE namespace=? AND external_job_id=?
            AND worker_id=? AND attempt_no=? AND fence_token=? AND operation='clara-result'
            AND request_key=? AND acknowledged IS NOT NULL''',
            (binding['namespace'], binding['external_job_id'], binding['worker_id'], binding['attempt_no'],
             binding['fence_token'], 'result-' + jid))
        return bool(result and json.loads(result['payload']).get('outcome') == 'completed_prepared')

    async def take(self):
        result = self.probe()
        return validate_snapshot(await result if inspect.isawaitable(result) else result)

    async def begin(self, jid):
        # Persist once, before any model action. Resuming a process must never
        # replace old activity with a new clean baseline for that old attempt.
        existing = self.store.one('SELECT snapshot FROM portal_windows_baselines WHERE job_id=?', (jid,))
        if existing:
            return json.loads(existing['snapshot']).get('baseline_issues', ['windows-baseline-unavailable'])
        try:
            value = await self.take()
            value['baseline_issues'] = baseline_issues(value)
        except Exception:
            value = {'baseline_issues': ['windows-baseline-unavailable']}
        self.store.execute('INSERT OR IGNORE INTO portal_windows_baselines VALUES(?,?)', (jid, json.dumps(value)))
        return value['baseline_issues']

    async def observe(self, jid):
        unknown, running = [], []
        row = self.store.one('SELECT snapshot FROM portal_windows_baselines WHERE job_id=?', (jid,))
        if not self.exclusive or not self.qualified:
            unknown.append('windows-handoff-not-qualified')
        if not row:
            return {'in_flight': [], 'unknown': unknown + ['windows-baseline-missing'], 'complete': False}
        baseline = json.loads(row['snapshot'])
        unknown.extend(baseline.get('baseline_issues', ['windows-baseline-unavailable']))
        try:
            current = await self.take()
            if any(current[k] != baseline.get(k) for k in ('session', 'boot', 'controller', 'owner')):
                unknown.append('windows-session-or-controller-changed')
            before = {process_key(p) for p in baseline.get('processes', [])}
            running.extend(f"windows-process:{p['pid']}:{p['created']}" for p in current['processes'] if process_key(p) not in before)
            windows = {window_key(w) for w in baseline.get('windows', [])}
            running.extend(f"windows-window:{w['handle']}:{w['pid']}" for w in current['windows'] if window_key(w) not in windows)
            running.extend(f"windows-print:{p['queue']}:{p['id']}" for p in current['print_jobs'])
        except Exception:
            unknown.append('windows-observation-unavailable')
        # No automatic reconciliation of an interrupted or failed task, even
        # if its applications disappeared. Its side effects still need review.
        if self.store.job(jid)['status'] not in {'completed', 'needs_review'}:
            unknown.append('windows-interrupted-task-needs-review')
        if not self.prepared_closeout(jid):
            unknown.append('windows-prepared-closeout-receipt-required')
        if unknown or running:
            self.clear_since.pop(jid, None)
        else:
            first = self.clear_since.setdefault(jid, self.clock())
            if self.clock() - first < 3:
                running.append('windows-settling')
        return {'in_flight': sorted(set(running)), 'unknown': sorted(set(unknown)),
                'complete': not running and not unknown}

    async def cleanup_hint(self, jid):
        row = self.store.one('SELECT snapshot FROM portal_windows_baselines WHERE job_id=?', (jid,))
        if not row:
            return None
        try:
            before = json.loads(row['snapshot'])
            current = await self.take()
            if any(current[k] != before.get(k) for k in ('session', 'boot', 'controller', 'owner')):
                return None
            old = {window_key(w) for w in before.get('windows', [])}
            names = {p['pid']: p.get('name', '') for p in current['processes']}
            windows = [{**w, 'application': names.get(w['pid'], '')} for w in current['windows']
                       if window_key(w) not in old and w['class'] not in SHELL_CLASSES | CONSOLE_CLASSES
                       and w['pid'] not in current['ancestors']]
            return windows[:12] or None
        except Exception:
            return None
