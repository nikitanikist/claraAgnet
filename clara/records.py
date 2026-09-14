"""Additive production-state schema. Existing conversations and jobs remain intact."""
SCHEMA = """
CREATE TABLE IF NOT EXISTS workflows (
 id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL UNIQUE REFERENCES conversations(id),
 kind TEXT NOT NULL, context TEXT NOT NULL, contract TEXT NOT NULL,
 limits TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', created REAL NOT NULL, updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_jobs (
 job_id TEXT PRIMARY KEY REFERENCES jobs(id), workflow_id TEXT NOT NULL REFERENCES workflows(id)
);
CREATE TABLE IF NOT EXISTS checkpoints (
 id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL REFERENCES workflows(id), job_id TEXT NOT NULL REFERENCES jobs(id),
 stage TEXT NOT NULL, status TEXT NOT NULL, evidence_ids TEXT NOT NULL, note TEXT NOT NULL, created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS checkpoints_workflow ON checkpoints(workflow_id, created);
CREATE TABLE IF NOT EXISTS evidence (
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), kind TEXT NOT NULL,
 subject TEXT NOT NULL, payload TEXT NOT NULL, verified INTEGER NOT NULL, created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS evidence_job ON evidence(job_id, created);
CREATE TABLE IF NOT EXISTS knowledge (
 id TEXT PRIMARY KEY, scope_key TEXT NOT NULL, library TEXT NOT NULL, title TEXT NOT NULL,
 metadata TEXT NOT NULL, content_hash TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL,
 UNIQUE(scope_key, library, content_hash)
);
CREATE TABLE IF NOT EXISTS knowledge_chunks (
 id INTEGER PRIMARY KEY, knowledge_id TEXT NOT NULL REFERENCES knowledge(id), ordinal INTEGER NOT NULL, text TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_search USING fts5(text, content='knowledge_chunks', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS knowledge_chunk_insert AFTER INSERT ON knowledge_chunks BEGIN
 INSERT INTO knowledge_search(rowid,text) VALUES(new.id,new.text); END;
CREATE TABLE IF NOT EXISTS memories (
 id TEXT PRIMARY KEY, origin_job TEXT NOT NULL REFERENCES jobs(id), scope_key TEXT NOT NULL,
 kind TEXT NOT NULL, title TEXT NOT NULL, application TEXT NOT NULL, build TEXT NOT NULL,
 payload TEXT NOT NULL, status TEXT NOT NULL, reviewed INTEGER NOT NULL DEFAULT 0,
 created REAL NOT NULL, updated REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS memory_scope ON memories(scope_key, application, status);
CREATE TABLE IF NOT EXISTS memory_uses (
 id TEXT PRIMARY KEY, memory_id TEXT NOT NULL REFERENCES memories(id), job_id TEXT NOT NULL REFERENCES jobs(id),
 started REAL NOT NULL, UNIQUE(memory_id,job_id)
);
CREATE TABLE IF NOT EXISTS memory_validations (
 id TEXT PRIMARY KEY, memory_id TEXT NOT NULL REFERENCES memories(id), job_id TEXT NOT NULL REFERENCES jobs(id),
 evidence_id TEXT REFERENCES evidence(id), case_key TEXT NOT NULL, success INTEGER NOT NULL, created REAL NOT NULL,
 UNIQUE(memory_id,job_id)
);
CREATE TABLE IF NOT EXISTS memory_audit (
 id INTEGER PRIMARY KEY, memory_id TEXT NOT NULL REFERENCES memories(id), action TEXT NOT NULL, note TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS operations (
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), scope_key TEXT NOT NULL,
 system TEXT NOT NULL, operation TEXT NOT NULL, external_key TEXT NOT NULL,
 request_hash TEXT NOT NULL, state TEXT NOT NULL, remote_id TEXT, result TEXT, created REAL NOT NULL, updated REAL NOT NULL,
 UNIQUE(scope_key,system,operation,external_key)
);
CREATE TABLE IF NOT EXISTS operation_audit (
 id INTEGER PRIMARY KEY,operation_id TEXT NOT NULL REFERENCES operations(id),action TEXT NOT NULL,note TEXT NOT NULL,created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS portal_assignments (
 external_id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, conversation_id TEXT NOT NULL REFERENCES conversations(id),
 job_id TEXT NOT NULL REFERENCES jobs(id), owner_key TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS portal_receipts (
 external_id TEXT PRIMARY KEY REFERENCES portal_assignments(external_id), acknowledged REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS execution_snapshots (
 job_id TEXT PRIMARY KEY REFERENCES jobs(id), last_tool TEXT, last_result TEXT, uncertain INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS portal_v1_outbox (
 id INTEGER PRIMARY KEY, namespace TEXT NOT NULL, external_job_id TEXT NOT NULL,
 worker_id TEXT NOT NULL, attempt_no INTEGER NOT NULL, fence_token INTEGER NOT NULL,
 operation TEXT NOT NULL, request_key TEXT NOT NULL, request_hash TEXT NOT NULL,
 payload TEXT NOT NULL, receipt TEXT, created REAL NOT NULL, acknowledged REAL,
 UNIQUE(namespace,external_job_id,worker_id,attempt_no,fence_token,operation,request_key)
);
CREATE INDEX IF NOT EXISTS portal_v1_pending ON portal_v1_outbox(namespace,acknowledged,id);
"""
