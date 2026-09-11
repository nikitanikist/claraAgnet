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
    store.event(conversation["id"], first["id"], "assistant", {"text": "The files are ready. I am adding the downloads."})
    files = []
    for name, text in (("clara-first-test.txt", "Clara is connected."), ("verification-notes.txt", "Synthetic browser test.")):
        (config.workspace / name).write_text(text)
        files.append(publish_artifact(config, store, first, name))
    store.event(conversation["id"], first["id"], "assistant", {"text": "Created and verified both files. Download them below."})
    store.status(first["id"], "completed")
    second = store.create_job(conversation["id"], "Where can I download them?", "ask", [])
    store.event(conversation["id"], second["id"], "assistant", {"text": "Use the file cards under the previous task."})
    store.status(second["id"], "completed")
    print(json.dumps({"url": f"http://127.0.0.1:{config.port}/#access=ui-fixture-only", "cid": conversation["id"],
                      "empty_cid": empty["id"], "first_job": first["id"], "second_job": second["id"], "files": files}), flush=True)
    uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False)).run(sockets=[sock])
