"""Exercise Windows-style file lifetime rules without requiring Windows."""
import sqlite3
from contextlib import contextmanager

import pytest

import clara.backup as backup_module
from clara.config import Config
from clara.instance import single_instance
from clara.store import Store


@pytest.mark.parametrize("snapshot_fails", [False, True])
def test_snapshot_connections_close_before_temporary_cleanup(tmp_path, monkeypatch, snapshot_fails):
    cfg = Config(tmp_path / "data")
    cfg.initialize()
    Store(cfg.data / "clara.sqlite3")
    original_connect = sqlite3.connect
    original_tempdir = backup_module.tempfile.TemporaryDirectory
    connections = []

    class TrackedConnection(sqlite3.Connection):
        closed = False

        def backup(self, destination, **kwargs):
            if snapshot_fails:
                raise sqlite3.OperationalError("snapshot failed")
            return super().backup(destination, **kwargs)

        def close(self):
            super().close()
            self.closed = True

    def connect(*args, **kwargs):
        connection = original_connect(*args, factory=TrackedConnection, **kwargs)
        connections.append(connection)
        return connection

    @contextmanager
    def windows_tempdir():
        with original_tempdir() as folder:
            try:
                yield folder
            finally:
                # Windows cannot remove a database while its connection owns a handle.
                assert len(connections) == 2
                assert all(connection.closed for connection in connections), "Database is still open at temporary cleanup"

    monkeypatch.setattr(backup_module.sqlite3, "connect", connect)
    monkeypatch.setattr(backup_module.tempfile, "TemporaryDirectory", windows_tempdir)
    try:
        if snapshot_fails:
            with pytest.raises(sqlite3.OperationalError, match="snapshot failed"):
                backup_module.backup(cfg, tmp_path / "backups")
            assert not list((tmp_path / "backups").glob("*.zip"))
        else:
            assert backup_module.backup(cfg, tmp_path / "backups").is_file()
        # A failed backup must also release Clara's application lock.
        with single_instance(cfg.data):
            pass
    finally:
        for connection in connections:
            connection.close()


def test_backup_refuses_an_actually_running_instance(tmp_path):
    cfg = Config(tmp_path / "data")
    cfg.initialize()
    with single_instance(cfg.data):
        with pytest.raises(RuntimeError, match="already running"):
            backup_module.backup(cfg, tmp_path / "backups")
    assert not list((tmp_path / "backups").glob("*.zip"))
