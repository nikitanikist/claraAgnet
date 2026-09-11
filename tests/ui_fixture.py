"""Serve synthetic artifact history through the real API, without model calls."""
import asyncio
import json
from pathlib import Path
import socket
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
import clara.app as app_module
from clara.config import Config
from clara.tools import publish_artifact
from clara.usage import UsageTracker
from claude_agent_sdk import ResultMessage


class NoModelManager:
    def __init__(self, config, store):
        self.active_job = None
        self.queue = asyncio.Queue()

    async def start(self):
        pass

    async def close(self):
        pass

    def pending_requests(self, cid):
        return []


async def fixture_auth(config=None):
    return {"connected": True, "plan": "UI test", "message": "Synthetic UI fixture; no model call."}


app_module.auth_status = fixture_auth
with tempfile.TemporaryDirectory(prefix="clara-ui-fixture-") as directory:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    config = Config(Path(directory), sock.getsockname()[1])
    app = app_module.create_app(config, manager_factory=NoModelManager, access_token="ui-fixture-only")
    store = app.state.store
    empty = store.create_conversation()
    conversation = store.create_conversation()
    first = store.create_job(conversation["id"], "Create two test files and attach them.", "ask", [])
    store.event(conversation['id'], first['id'], 'tool', {'id':'fixture-tool', 'name':'mcp__windows__App', 'input':'{"mode":"switch","name":"Example"}'})
    store.event(conversation['id'], first['id'], 'tool_done', {'id':'fixture-tool', 'name':'mcp__windows__App', 'failed':True,
        'duration_ms':1250, 'output_excerpt':'Application Example not found. <img src=x>', 'output_truncated':False})
    store.event(conversation["id"], first["id"], "assistant", {"text": "The files are ready. I am adding the downloads."})
    files = []
    for name, text in (("clara-first-test.txt", "Clara is connected."), ("verification-notes.txt", "Synthetic browser test.")):
        (config.workspace / name).write_text(text)
        files.append(publish_artifact(config, store, first, name))
    store.event(conversation["id"], first["id"], "assistant", {"text": "Created and verified both files. Download them below."})
    usage = UsageTracker().result(ResultMessage(subtype="success", duration_ms=12000,
        duration_api_ms=9000, is_error=False, num_turns=4, session_id="synthetic", total_cost_usd=0.0314,
        model_usage={"synthetic-model": {"inputTokens": 1000, "outputTokens": 200,
            "cacheReadInputTokens": 3000, "cacheCreationInputTokens": 800, "costUSD": 0.0314}}), 13000, .10)
    store.execute("UPDATE jobs SET usage=? WHERE id=?", (json.dumps(usage), first["id"]))
    store.event(conversation["id"], first["id"], "usage", usage)
    store.status(first["id"], "completed")
    second = store.create_job(conversation["id"], "Where can I download them?", "ask", [])
    store.event(conversation["id"], second["id"], "assistant", {"text": "Use the file cards under the previous task."})
    # Legacy usage must upgrade on history replay without a migration/model call.
    usage = {"tokens": {"input_tokens": 90, "output_tokens": 10}, "sdk_estimated_usd": .002,
             "turns": 1, "duration_ms": 1000}
    store.execute("UPDATE jobs SET usage=? WHERE id=?", (json.dumps(usage), second["id"]))
    store.event(conversation["id"], second["id"], "usage", usage)
    store.status(second["id"], "completed")
    print(json.dumps({"url": f"http://127.0.0.1:{config.port}/#access=ui-fixture-only", "cid": conversation["id"],
                      "empty_cid": empty["id"], "first_job": first["id"], "second_job": second["id"], "files": files}), flush=True)
    uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False)).run(sockets=[sock])
