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
from .portal_bindings import SOFTWARE_PERMISSIONS

SHELL_CLASSES = {'Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd'}
CONSOLE_CLASSES = {'ConsoleWindowClass', 'CASCADIA_HOSTING_WINDOW_CLASS'}
SHELL_HELPER_CLASSES = {'ThumbnailDeviceHelperWnd', 'EdgeUiInputTopWndClass'}


def shell_surface(snapshot, window):
    return (window['class'] in SHELL_CLASSES or
            (window['class'] in SHELL_HELPER_CLASSES and snapshot.get('shell_pid', 0) > 0
             and window['pid'] == snapshot['shell_pid']))


def same_execution_session(current, baseline):
    # psutil's Windows boot-time estimate jitters by milliseconds between calls.
    # The controller PID + exact creation time, account and session must still
    # match. A tiny clock-estimation change is not a new Windows boot.
    return (all(current[k] == baseline.get(k) for k in ('session', 'controller', 'owner')) and
            type(baseline.get('boot')) in {int, float} and
            abs(current['boot'] - baseline['boot']) <= 2)


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


async def native_reap(root_pid, since, protected):
    """End leftover executor processes under root_pid through the desktop Python (which has psutil)."""
    command = desktop_command()
    if os.name != 'nt' or not command:
        raise ValueError('Windows executor cleanup is unavailable.')
    with tempfile.TemporaryFile() as output:
        process = await asyncio.create_subprocess_exec(command[0], str(Path(__file__).with_name('windows_reap.py')),
            str(int(root_pid)), repr(float(since)), *(str(int(pid)) for pid in protected),
            env=clean_environment(), stdout=output, stderr=asyncio.subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            await asyncio.wait_for(process.wait(), 30)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        output.seek(0)
        data = output.read(100_001)
        if process.returncode or len(data) > 100_000:
            raise ValueError('Windows executor cleanup did not finish completely.')
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
    if 'ui_process_ids' in value and (not isinstance(value['ui_process_ids'], list)
            or len(value['ui_process_ids']) > 10000
            or any(type(pid) is not int or pid < 1 for pid in value['ui_process_ids'])):
        raise ValueError('Windows application surface identity is incomplete.')
    for process in value['processes']:
        if (type(process.get('pid')) is not int or process['pid'] < 1 or
                type(process.get('created')) not in {int, float} or not math.isfinite(process['created'])):
            raise ValueError('A Windows process lacks its creation identity.')
        if 'parent' in process and (type(process['parent']) is not int or process['parent'] < 0):
            raise ValueError('A Windows process has an unreadable parent identity.')
        if 'parent_created' in process and (type(process['parent_created']) not in {int, float}
                                            or not math.isfinite(process['parent_created'])):
            raise ValueError('A Windows process has an unreadable parent identity.')
    return value


def process_key(row):
    return (row['pid'], row['created'])


def window_key(row):
    return (row['handle'], row['pid'], row['class'])


# Windows starts these for itself as a side effect of ordinary use (typing opens
# ctfmon and the touch-keyboard hosts; consoles get a conhost; hosted apps get
# a broker). They are never a task's unfinished work and never a leftover.
WINDOWS_HELPERS = {'ctfmon.exe', 'tabtip.exe', 'tabtip32.exe', 'textinputhost.exe', 'runtimebroker.exe',
                   'dllhost.exe', 'backgroundtaskhost.exe', 'searchhost.exe', 'shellexperiencehost.exe',
                   'startmenuexperiencehost.exe', 'sihost.exe', 'conhost.exe', 'openconsole.exe',
                   'applicationframehost.exe', 'smartscreen.exe', 'wmiprvse.exe', 'taskhostw.exe',
                   'fontdrvhost.exe', 'dwm.exe', 'audiodg.exe'}
TASK_APPLICATIONS = {'chrome.exe', 'msedge.exe', 't1txp.exe', 'profile.exe', 'winword.exe', 'excel.exe',
                     'acrord32.exe', 'acrobat.exe'}
# The tax applications start their own background updaters when they launch.
# They are the vendor's housekeeping, not Clara's work: she never starts one
# deliberately, it carries no client data, and it keeps running after the
# application closes. Observed on the live machine: launching ProFile spawned
# Intuit.PCG.ProFile.AutoUpdate, which then held the worker for review after a
# closeout that had otherwise finished cleanly. Their presence says nothing
# about whether a task finished, so they are never a leftover.
VENDOR_SERVICES = {'intuit.pcg.profile.autoupdate.exe', 'profileupdate.exe',
                   'cchupdate.exe', 'taxprepupdate.exe'}
# A task's own last actions and the moment its end is recorded are not the same
# instant. Only this much later still counts as started by the task itself.
AFTER_TASK_GRACE_S = 10


def baseline_issues(snapshot):
    """Starting conditions that block a task: Clara's own printing still active."""
    issues = []
    if snapshot['print_jobs']:
        issues.append('windows-baseline-printing-active')
    return issues


def baseline_notes(snapshot):
    """Programs already running before the task. They belong to whoever opened them.

    A chat client, a browser or a tax application that predates the task is
    not Clara's leftover and never holds the worker; it is kept in the baseline
    for the audit trail and for the operator's cleanup review.
    """
    notes = []
    # Console hosts are retained so the operator can keep Clara's startup PowerShell open.
    if any(not shell_surface(snapshot, w) and w['class'] not in CONSOLE_CLASSES for w in snapshot['windows']):
        notes.append('pre-existing-application-windows')
    if any(p.get('name', '').casefold() in TASK_APPLICATIONS for p in snapshot['processes']):
        notes.append('pre-existing-task-application')
    return notes


def own_launch_chain(process, current):
    """The restarted worker itself, its launchers, or a helper a launcher opened (its console).

    The worker's own descendants are NOT covered: they are the task's executors.
    """
    ancestors = set(current.get('ancestors', []))
    controller = (current.get('controller') or [None])[0]
    parent = process.get('parent') or 0
    return process['pid'] in ancestors or (parent in ancestors and parent != controller)


def task_started_processes(current, baseline, ended=None):
    """Processes that appeared after the baseline and are attributable to the task.

    A leftover is something Clara started that is still running. A new process
    is not hers when its parent (or that parent's parent, and so on) is a
    program that was already running before the task and is neither the
    worker's own launch chain nor the Windows shell (every Explorer process):
    the helpers a pre-existing browser or chat client spawns for itself are
    that program's business.

    A parent is identified, not merely named by pid: Windows leaves a dead
    creator's pid on its children and hands that pid to the next process, so a
    parent row counts only when its creation time matches the recorded parent
    identity, or at least precedes the child's. A process whose parent cannot
    be read, has already exited, or lives outside this session stays attributed
    to the task, so nothing Clara launched can be waved through once its
    launcher is gone.

    `ended` is when the task itself finished. Work Clara left behind was
    started while she was working: a program that first appeared minutes or
    hours after she stopped belongs to whatever started it then, even when its
    own launcher has since exited and cannot be read. Such a process counts
    only as the descendant of one of her real leftovers, which keeps a leftover
    that spawns children after the fact fully visible.
    """
    before = {process_key(p) for p in baseline.get('processes', [])}
    by_pid = {p['pid']: p for p in current['processes']}
    own = set(current.get('ancestors', [])) | {current.get('shell_pid', 0)}
    own |= {p['pid'] for p in current['processes'] if str(p.get('name', '')).casefold() == 'explorer.exe'}

    def parent_of(p):
        parent = p.get('parent') or 0
        row = by_pid.get(parent) if parent else None
        if row is None:
            return None
        stamp = p.get('parent_created')
        if stamp is not None and abs(row['created'] - stamp) > 0.01:
            return None  # the pid was reused; the real parent is gone
        if stamp is None and row['created'] > p['created']:
            return None  # a parent is always created before its child
        return row

    fresh = [p for p in current['processes'] if process_key(p) not in before]
    foreign, settled = set(), False
    while not settled:
        settled = True
        for p in fresh:
            parent = p.get('parent') or 0
            if p['pid'] in foreign or not parent or parent in own:
                continue
            row = parent_of(p)
            if row is None:
                continue
            if row['pid'] in foreign or process_key(row) in before:
                foreign.add(p['pid'])
                settled = False

    # Nothing created after the task ended is its leftover unless it descends
    # from one. The grace absorbs the moment between the last thing Clara did
    # and the recorded end of the task.
    late = set()
    if ended is not None:
        cutoff = ended + AFTER_TASK_GRACE_S
        late = {p['pid'] for p in fresh if p['pid'] not in foreign and p['created'] > cutoff}
        settled = False
        while not settled:
            settled = True
            for p in fresh:
                if p['pid'] not in late:
                    continue
                row = parent_of(p)
                if row is None or process_key(row) in before:
                    continue
                if row['pid'] not in foreign and row['pid'] not in late:
                    late.discard(p['pid'])
                    settled = False
    return [p for p in fresh if p['pid'] not in foreign and p['pid'] not in late]


class WindowsHandoff:
    def __init__(self, store, *, exclusive=False, qualified=False, probe=native_snapshot, clock=time.monotonic,
                 reaper=native_reap):
        self.store, self.exclusive, self.qualified = store, exclusive, qualified
        self.probe, self.clock, self.reaper = probe, clock, reaper
        self.clear_since = {}

    async def reap_executors(self, jid, root_pid, since):
        """End the model/script executors a finished or stopped task left running.

        A bare cancellation of the SDK session can orphan the Claude CLI and its
        MCP bridges; observe() would then report them as unfinished execution
        for ever. Only executor processes under the task's CLI (or, when its PID
        is unknown, under this worker) that started with the task are ended.
        Applications stay open for the operator's review; this never authorizes
        a handoff or changes any job state.
        """
        root = int(root_pid) if root_pid else os.getpid()
        try:
            result = await self.reaper(root, float(since), [os.getpid()])
        except Exception as error:
            result = {'root': root, 'error': type(error).__name__, 'terminated': [], 'failed': []}
        job = self.store.job(jid)
        if job:
            self.store.event(job['conversation_id'], jid, 'executors_reaped', result)
        return result

    def general_task(self, jid):
        row = self.store.one('SELECT claim_json FROM portal_v1_attempts WHERE local_job_id=?', (jid,))
        return bool(row and json.loads(row['claim_json']).get('kind') == 'general')

    def completed_general(self, jid):
        binding = self.store.one('SELECT * FROM portal_v1_attempts WHERE local_job_id=?', (jid,))
        if not binding or not self.general_task(jid) or self.store.job(jid)['status'] != 'completed':
            return False
        row = self.store.one('''SELECT payload,receipt FROM portal_v1_outbox WHERE namespace=? AND external_job_id=?
            AND worker_id=? AND attempt_no=? AND fence_token=? AND operation='clara-result'
            AND request_key=? AND acknowledged IS NOT NULL''',
            (binding['namespace'], binding['external_job_id'], binding['worker_id'], binding['attempt_no'],
             binding['fence_token'], 'result-' + jid))
        if not row:
            return False
        payload, receipt = json.loads(row['payload']), json.loads(row['receipt'])
        return (payload.get('outcome') == 'completed_prepared' and receipt.get('result_recorded') is True
                and receipt.get('job_state') == 'completed_prepared'
                and receipt.get('handoff', {}).get('status') == 'not_applicable')

    def prepared_closeout(self, jid):
        binding = self.store.one('SELECT * FROM portal_v1_attempts WHERE local_job_id=?', (jid,))
        if not binding:
            return False
        claim = json.loads(binding['claim_json'])
        permission = SOFTWARE_PERMISSIONS.get((claim.get('closeout') or {}).get('software'))
        if claim['kind'] != 'closeout' or permission is None or permission not in claim['scope']['permissions']:
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
            # Programs already open in the account are not another task and
            # not Clara's leftovers. Their identities stay in the immutable
            # baseline; only her own printing blocks a start.
            value['baseline_issues'] = baseline_issues(value)
            value['baseline_notes'] = baseline_notes(value)
        except Exception:
            value = {'baseline_issues': ['windows-baseline-unavailable']}
        self.store.execute('INSERT OR IGNORE INTO portal_windows_baselines VALUES(?,?)', (jid, json.dumps(value)))
        return value['baseline_issues']

    async def observe(self, jid):
        if self.general_task(jid):
            return await self.observe_general(jid)
        unknown, running = [], []
        # Every locally ended attempt without a successful closeout receipt is
        # reviewed the same way. 'incomplete' means a workflow stage's evidence
        # stopped matching after the model finished; 'needs_review' and
        # 'completed' mean the model finished and the portal has the last word.
        # Their desktop leftovers are unresolved observations for the operator,
        # never proof of execution, and a restarted worker is never its own
        # unfinished work.
        interrupted = self.store.job(jid)['status'] in {'failed', 'stopped', 'interrupted', 'cancelled',
                                                        'incomplete', 'needs_review', 'completed'}
        row = self.store.one('SELECT snapshot FROM portal_windows_baselines WHERE job_id=?', (jid,))
        if not self.exclusive or not self.qualified:
            unknown.append('windows-handoff-not-qualified')
        if not row:
            return {'in_flight': [], 'unknown': unknown + ['windows-baseline-missing'], 'complete': False}
        baseline = json.loads(row['snapshot'])
        unknown.extend(baseline.get('baseline_issues', ['windows-baseline-unavailable']))
        try:
            current = await self.take()
            if not same_execution_session(current, baseline):
                unknown.append('windows-session-or-controller-changed')
            # A restarted worker in the same logon can still have orphaned executors
            # of the old attempt; a new logon or boot cannot.
            same_logon = (current['session'] == baseline.get('session')
                          and type(baseline.get('boot')) in {int, float} and abs(current['boot'] - baseline['boot']) <= 2)
            # A restarted worker has a new launch chain that is not the old attempt's
            # work. With the same controller still running, a new process behind an
            # ancestor's pid is somebody else's work and stays visible.
            restarted = current['controller'] != baseline.get('controller')
            # After a stopped attempt, an open app Clara started is an unresolved
            # observation, not proof that it is still executing a tool. Let the
            # existing operator reconciliation review those exact identities.
            # Detached model/script executors and printing still block
            # continuation. Programs that predate the task, and the helpers they
            # spawn for themselves, are not hers (task_started_processes). The
            # restarted observer and its own launch ancestors cannot be
            # unfinished work from the old attempt. Its changed identity stays
            # in unknown above; this never grants automatic handoff. After a
            # new Windows logon or boot, nothing from the old attempt survived,
            # so every process of the new session is an observation to review,
            # not execution still in flight.
            executors = {'python.exe', 'pythonw.exe', 'node.exe', 'claude.exe',
                         'powershell.exe', 'pwsh.exe', 'cmd.exe', 'wscript.exe', 'cscript.exe'}
            for p in task_started_processes(current, baseline, self.store.job(jid)['finished']):
                if p.get('name', '').casefold() in WINDOWS_HELPERS | VENDOR_SERVICES:
                    continue
                if interrupted and restarted and own_launch_chain(p, current):
                    continue
                ref = f"windows-process:{p['pid']}:{p['created']}"
                if interrupted and (not same_logon or p.get('name', '').casefold() not in executors):
                    unknown.append(ref)
                else:
                    running.append(ref)
            windows = {window_key(w) for w in baseline.get('windows', [])}
            for w in current['windows']:
                if window_key(w) in windows or shell_surface(current, w):
                    continue
                if interrupted and w['pid'] in current['ancestors'] and w['class'] in CONSOLE_CLASSES:
                    continue
                (unknown if interrupted else running).append(f"windows-window:{w['handle']}:{w['pid']}")
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

    async def observe_general(self, jid):
        """A finished ordinary request may leave its requested app visible.

        Called alongside the runtime's outstanding-tool/operation inventory.
        It never releases interrupted work or an unacknowledged result. The
        separate TaxPrep qualification and document checks are unchanged.
        """
        unknown, running = [], []
        if not self.exclusive:
            unknown.append('windows-dedicated-session-required')
        row = self.store.one('SELECT snapshot FROM portal_windows_baselines WHERE job_id=?', (jid,))
        if not row:
            return {'in_flight': [], 'unknown': unknown + ['windows-baseline-missing'], 'complete': False}
        baseline = json.loads(row['snapshot'])
        unknown.extend(baseline.get('baseline_issues', ['windows-baseline-unavailable']))
        if not self.completed_general(jid):
            unknown.append('windows-completed-general-receipt-required')
        try:
            current = await self.take()
            if not same_execution_session(current, baseline):
                unknown.append('windows-session-or-controller-changed')
            # A restarted worker's own launch chain is never the old request's
            # unfinished work (the same rule the closeout observer applies).
            restarted = current['controller'] != baseline.get('controller')
            visible = set(current.get('ui_process_ids', [])) | {w['pid'] for w in current['windows']}
            controllers = {'python.exe', 'pythonw.exe', 'node.exe', 'claude.exe', 'powershell.exe',
                           'pwsh.exe', 'cmd.exe', 'wscript.exe', 'cscript.exe'}
            for p in task_started_processes(current, baseline, self.store.job(jid)['finished']):
                if p.get('name', '').casefold() in WINDOWS_HELPERS | VENDOR_SERVICES:
                    continue
                if restarted and own_launch_chain(p, current):
                    continue
                if p['pid'] not in visible or p.get('name', '').casefold() in controllers:
                    running.append(f"windows-process:{p['pid']}:{p['created']}")
            running.extend(f"windows-print:{p['queue']}:{p['id']}" for p in current['print_jobs'])
        except Exception:
            unknown.append('windows-observation-unavailable')
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
            if not same_execution_session(current, before):
                return None
            old = {window_key(w) for w in before.get('windows', [])}
            names = {p['pid']: p.get('name', '') for p in current['processes']}
            windows = [{**w, 'application': names.get(w['pid'], '')} for w in current['windows']
                       if window_key(w) not in old and not shell_surface(current, w) and w['class'] not in CONSOLE_CLASSES
                       and w['pid'] not in current['ancestors']]
            return windows[:12] or None
        except Exception:
            return None
