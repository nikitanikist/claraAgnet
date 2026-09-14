"""Native API smoke tests. CI does not qualify the firm's interactive RDP."""
import os
import subprocess
import sys

import pytest

from clara.windows_activity import snapshot

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Requires real Windows APIs')


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
        assert all(set(p) == {'pid', 'created', 'name'} for p in observed['processes'])
        assert all(set(j) == {'queue', 'id', 'status'} for j in observed['print_jobs'])
        assert isinstance(observed['interactive'], bool)
    finally:
        child.terminate()
        child.wait(timeout=5)
    assert all(p['pid'] != child.pid for p in snapshot(os.getpid())['processes'])
