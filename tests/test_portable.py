import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import zipfile

import pytest

spec = importlib.util.spec_from_file_location('portable', Path(__file__).parents[1] / 'scripts/install-portable.py')
portable = importlib.util.module_from_spec(spec)
spec.loader.exec_module(portable)


@pytest.fixture
def embedded(tmp_path):
    source = tmp_path / 'old-python'
    source.mkdir()
    for name in ('python.exe', 'python312.dll', 'python312.zip', '_ssl.pyd', 'LICENSE.txt'):
        (source / name).write_bytes(b'fixture')
    (source / 'python312._pth').write_text('python312.zip\n.\nC:\\old-client-app\n')
    (source / 'client-data.txt').write_text('private fixture')
    return source


def test_copy_keeps_original_and_excludes_old_application(embedded, tmp_path):
    before = {p.name: p.read_bytes() for p in embedded.iterdir()}
    result = portable.prepare_runtime(embedded, tmp_path / 'app/.portable-python', (3, 12, 8))
    assert {p.name: p.read_bytes() for p in embedded.iterdir()} == before
    assert result.exists()
    assert not (result.parent / 'client-data.txt').exists()
    paths = (result.parent / 'python312._pth').read_text().splitlines()
    assert paths == ['python312.zip', '.', 'Lib/site-packages', '..', 'import site']
    assert not (result.parent / portable.READY).exists()


def test_refuses_overlap_and_unowned_destination(embedded, tmp_path):
    for destination in (embedded, embedded / 'copy', tmp_path):
        with pytest.raises(ValueError, match='separate'):
            portable.prepare_runtime(embedded, destination, (3, 12, 8))
    other = tmp_path / 'unrelated'
    other.mkdir()
    (other / 'keep').write_text('keep')
    with pytest.raises(ValueError, match='unrelated'):
        portable.prepare_runtime(embedded, other, (3, 12, 8))
    assert (other / 'keep').read_text() == 'keep'


def test_retry_preserves_completed_copy_and_refuses_version_change(embedded, tmp_path):
    target = tmp_path / 'app/.portable-python'
    executable = portable.prepare_runtime(embedded, target, (3, 12, 8))
    (target / portable.READY).write_text('complete')
    assert portable.prepare_runtime(embedded, target, (3, 12, 8)) == executable
    assert (target / portable.READY).exists()
    with pytest.raises(ValueError, match='another Python'):
        portable.prepare_runtime(embedded, target, (3, 12, 9))


def test_pip_checksum_and_archive_path_controls(tmp_path, monkeypatch):
    wheel = tmp_path / 'pip.whl'
    wheel.write_bytes(b'wrong download')
    with pytest.raises(ValueError, match='checksum'):
        portable.extract_pip(wheel, tmp_path / 'pip')
    with zipfile.ZipFile(wheel, 'w') as archive:
        archive.writestr('../escape.txt', 'should not be extracted')
    monkeypatch.setattr(portable, 'PIP_SHA256', hashlib.sha256(wheel.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match='Invalid path'):
        portable.extract_pip(wheel, tmp_path / 'pip')
    assert not (tmp_path / 'escape.txt').exists()


def test_failed_verification_clears_ready_marker(embedded, tmp_path, monkeypatch):
    python = portable.prepare_runtime(embedded, tmp_path / 'app/.portable-python', (3, 12, 8))
    requirements = tmp_path / 'requirements'
    requirements.write_text('example==1.0\n')
    fingerprint = hashlib.sha256(requirements.read_bytes() + portable.PIP_SHA256.encode()).hexdigest()
    (python.parent / portable.READY).write_text(json.dumps({'requirements_sha256': fingerprint}))
    def fail(argv, **kwargs):
        raise subprocess.CalledProcessError(1, argv)
    monkeypatch.setattr(portable, 'run', fail)
    with pytest.raises(subprocess.CalledProcessError):
        portable.provision(python, tmp_path / 'runner', requirements, 'core')
    assert not (python.parent / portable.READY).exists()


def test_dependency_changes_reinstall_after_git_update(embedded, tmp_path, monkeypatch):
    python = portable.prepare_runtime(embedded, tmp_path / 'app/.portable-python', (3, 12, 8))
    requirements = tmp_path / 'requirements'
    requirements.write_text('example==1.0\n')
    commands = []
    monkeypatch.setattr(portable, 'run', lambda argv, **kwargs: commands.append(argv))
    portable.provision(python, tmp_path / 'runner', requirements, 'core')
    assert sum('install' in cmd for cmd in commands) == 1
    commands.clear()
    portable.provision(python, tmp_path / 'runner', requirements, 'core')
    assert not any('install' in cmd for cmd in commands)
    requirements.write_text('example==2.0\n')
    commands.clear()
    portable.provision(python, tmp_path / 'runner', requirements, 'core')
    assert sum('install' in cmd for cmd in commands) == 1


def test_desktop_requires_successful_portable_setup(tmp_path, monkeypatch):
    import clara.connectors as connectors
    monkeypatch.setattr(connectors, 'PROJECT', tmp_path)
    directory = tmp_path / '.portable-desktop'
    directory.mkdir()
    (directory / 'python.exe').touch()
    assert connectors.desktop_command() is None
    (directory / '.clara-ready').touch()
    assert connectors.desktop_command() == (str(directory / 'python.exe'), [str(tmp_path / 'clara/windows_bridge.py')])


def test_updating_owned_core_uses_existing_interpreter_without_copying_over_it(embedded,tmp_path,monkeypatch):
    root=tmp_path/'app';monkeypatch.setattr(portable,'ROOT',root)
    python=portable.prepare_runtime(embedded,root/'.portable-python',(3,12,8))
    before=python.read_bytes()
    assert portable.core_runtime(python.parent,(3,12,8))==python
    assert python.read_bytes()==before
    (python.parent/portable.OWNER).unlink()
    with pytest.raises(ValueError,match='Clara-owned'): portable.core_runtime(python.parent,(3,12,8))
