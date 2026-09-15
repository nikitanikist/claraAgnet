from types import SimpleNamespace

import pytest

from clara.windows_activity import own_probe_console


@pytest.mark.parametrize('change,expected', [
    ({}, True),
    ({'parent': 8}, False),
    ({'created': 99}, False),
    ({'name': 'python.exe'}, False),
    ({'location': 'untrusted'}, False),
])
def test_only_the_exact_observers_system_console_is_excluded(tmp_path, change, expected):
    values = {'parent': 7, 'created': 101, 'name': 'conhost.exe', 'location': 'System32'} | change
    process = SimpleNamespace(
        ppid=lambda: values['parent'], create_time=lambda: values['created'],
        name=lambda: values['name'],
        exe=lambda: str(tmp_path / values['location'] / 'conhost.exe'))
    assert own_probe_console(process, 7, 100, str(tmp_path)) is expected
