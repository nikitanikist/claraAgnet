"""Native API smoke tests. CI does not qualify the firm's interactive RDP."""
import os
import json
import subprocess
import sys

import pytest

from clara.windows_activity import snapshot

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Requires real Windows APIs')


def test_hidden_probe_does_not_count_its_own_console_as_application_work():
    # RDP creates a conhost child even with CREATE_NO_WINDOW. The ordinary
    # background process below must remain visible while the probe's own
    # console helper is omitted.
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                             creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        code = (
            'import os,json,psutil;from clara.windows_activity import snapshot;'
            f'value=snapshot({os.getpid()});'
            "helpers=[p.pid for p in psutil.Process().children() if p.name().lower()=='conhost.exe'];"
            "print(json.dumps({'snapshot':value,'helpers':helpers,'probe':os.getpid()}))"
        )
        run = subprocess.run([sys.executable, '-c', code], capture_output=True,
                             text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        assert run.returncode == 0, run.stderr
        value = json.loads(run.stdout)
        pids = {p['pid'] for p in value['snapshot']['processes']}
        assert child.pid in pids
        assert value['probe'] not in pids
        assert not pids.intersection(value['helpers'])
    finally:
        child.terminate()
        child.wait(timeout=5)


def test_native_probe_tracks_a_background_process_without_client_content():
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                             creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        observed = snapshot(os.getpid())
        assert observed['version'] == 1
        assert observed['controller'][0] == os.getpid()
        assert len(observed['owner']) == 64
        assert any(p['pid'] == child.pid and p['created'] > 0 for p in observed['processes'])
        assert all(set(w) == {'handle', 'pid', 'class'} for w in observed['windows'])
        assert all(set(p) == {'pid', 'created', 'name', 'parent'} for p in observed['processes'])
        assert all(set(j) == {'queue', 'id', 'status'} for j in observed['print_jobs'])
        assert isinstance(observed['interactive'], bool)
        assert isinstance(observed['ui_process_ids'], list)
        assert {w['pid'] for w in observed['windows']} <= set(observed['ui_process_ids'])
    finally:
        child.terminate()
        child.wait(timeout=5)
    assert all(p['pid'] != child.pid for p in snapshot(os.getpid())['processes'])


def test_native_probe_queries_token_when_wts_omits_own_process_sid(monkeypatch):
    import win32ts
    enumerate_processes = win32ts.WTSEnumerateProcesses
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                             creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        def without_child_sid():
            return [(session, pid, name, None if pid == child.pid else sid)
                    for session, pid, name, sid in enumerate_processes()]
        monkeypatch.setattr(win32ts, 'WTSEnumerateProcesses', without_child_sid)
        observed = snapshot(os.getpid())
        assert any(p['pid'] == child.pid for p in observed['processes'])
        assert f'process-owner-unreadable:{child.pid}' not in observed['errors']
        assert all(set(p) == {'pid', 'name'} for p in observed['unresolved_processes'])
        assert all(set(w) == {'handle', 'pid', 'class', 'width', 'height'}
                   for w in observed['window_details'])
        details = {w['handle']: w for w in observed['window_details']}
        assert all(details[w['handle']]['width'] > 0 and details[w['handle']]['height'] > 0
                   for w in observed['windows'])
    finally:
        child.terminate()
        child.wait(timeout=5)


def test_unreadable_owner_is_still_tracked_by_process_creation_identity(monkeypatch):
    import psutil
    import win32api
    import win32ts
    enumerate_processes = win32ts.WTSEnumerateProcesses
    open_process = win32api.OpenProcess
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                             creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        def without_child_sid():
            return [(session, pid, name, None if pid == child.pid else sid)
                    for session, pid, name, sid in enumerate_processes()]
        def deny_child_token(access, inherit, pid):
            if pid == child.pid:
                raise PermissionError('Synthetic owner-query denial')
            return open_process(access, inherit, pid)
        monkeypatch.setattr(win32ts, 'WTSEnumerateProcesses', without_child_sid)
        monkeypatch.setattr(win32api, 'OpenProcess', deny_child_token)
        observed = snapshot(os.getpid())
        assert any(p['pid'] == child.pid and p['created'] > 0 for p in observed['processes'])
        assert any(p['pid'] == child.pid for p in observed['unresolved_processes'])
        assert not any(str(child.pid) in error for error in observed['errors'])
        create_time = psutil.Process.create_time
        def read_creation(process):
            if process.pid == child.pid:
                raise psutil.AccessDenied(child.pid)
            return create_time(process)
        monkeypatch.setattr(psutil.Process, 'create_time', read_creation)
        incomplete = snapshot(os.getpid())
        assert f'process-unreadable:{child.pid}' in incomplete['errors']
        assert all(p['pid'] != child.pid for p in incomplete['processes'])
    finally:
        child.terminate()
        child.wait(timeout=5)
