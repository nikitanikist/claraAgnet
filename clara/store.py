"""Durable events and jobs; a restart never replays a potentially completed action."""
import json
import sqlite3
import time
import uuid
from .records import SCHEMA
from contextlib import contextmanager


def new_id():
    return uuid.uuid4().hex


class Store:
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, created REAL NOT NULL, session_id TEXT);
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id),
                prompt TEXT NOT NULL, status TEXT NOT NULL, mode TEXT NOT NULL,
                created REAL NOT NULL, finished REAL, usage TEXT, attachments TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_jobs_conversation ON jobs(conversation_id, created);
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id),
                job_id TEXT, kind TEXT NOT NULL, data TEXT NOT NULL, created REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_events_conversation_id ON events(conversation_id, id);
            CREATE TABLE IF NOT EXISTS files (
                id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id),
                job_id TEXT, kind TEXT NOT NULL, name TEXT NOT NULL, path TEXT NOT NULL,
                size INTEGER NOT NULL, created REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_files_conversation ON files(conversation_id, created);
            PRAGMA optimize;
            """)
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def execute(self, sql, args=()):
        with self.connect() as db:
            return db.execute(sql, args).rowcount

    def rows(self, sql, args=()):
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, args)]

    def one(self, sql, args=()):
        rows = self.rows(sql, args)
        return rows[0] if rows else None

    def conversation(self, cid):
        return self.one("SELECT * FROM conversations WHERE id=?", (cid,))

    def create_conversation(self, title="New conversation"):
        cid = new_id()
        self.execute("INSERT INTO conversations VALUES (?,?,?,NULL)", (cid, title, time.time()))
        return self.conversation(cid)

    def event(self, cid, job_id, kind, data):
        with self.connect() as db:
            cursor = db.execute("INSERT INTO events(conversation_id,job_id,kind,data,created) VALUES(?,?,?,?,?)",
                                (cid, job_id, kind, json.dumps(data), time.time()))
            return cursor.lastrowid

    def events(self, cid, after=0):
        rows = self.rows("SELECT * FROM events WHERE conversation_id=? AND id>? ORDER BY id LIMIT 1000", (cid, after))
        for row in rows:
            row["data"] = json.loads(row["data"])
        return rows

    def create_job(self, cid, prompt, mode, attachments):
        jid = new_id()
        self.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,NULL,NULL,?)",
                     (jid, cid, prompt, "queued", mode, time.time(), json.dumps(attachments)))
        self.event(cid, jid, "user", {"text": prompt, "attachments": attachments})
        self.event(cid, jid, "status", {"status": "queued"})
        if self.conversation(cid)["title"] == "New conversation":
            self.execute("UPDATE conversations SET title=? WHERE id=?", (prompt[:65], cid))
        return self.job(jid)

    def job(self, jid):
        return self.one("SELECT * FROM jobs WHERE id=?", (jid,))

    def status(self, jid, status, **details):
        job = self.job(jid)
        terminal = status in {"completed", "failed", "cancelled", "interrupted", "incomplete", "needs_review"}
        self.execute("UPDATE jobs SET status=?,finished=? WHERE id=?", (status, time.time() if terminal else None, jid))
        self.event(job["conversation_id"], jid, "status", {"status": status, **details})

    def recover(self):
        for job in self.rows("SELECT * FROM jobs WHERE status IN ('queued','running','waiting','cancelling')"):
            self.status(job["id"], "interrupted", message="Clara restarted. Inspect the last result before continuing; this task was not replayed.")
