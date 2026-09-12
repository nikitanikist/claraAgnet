import asyncio
import json
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, Response
from pydantic import BaseModel, Field

from . import __version__
from .agent import AgentManager
from .auth import auth_status
from .config import PACKAGE, atomic_json
from .connectors import connector_status, desktop_ready
from .skills import list_skills, save_skill, import_skill, validate_name
from .store import Store, new_id
from .usage import job_usage, normalize_usage, conversation_usage, usage_csv


class MessageInput(BaseModel):
    text: str = Field(min_length=1, max_length=50000)
    mode: str | None = None
    attachments: list[str] = Field(default_factory=list, max_length=20)


class AnswerInput(BaseModel):
    answer: str = Field(min_length=1, max_length=20000)


class SkillInput(BaseModel):
    content: str = Field(min_length=1, max_length=200000)


class SettingsInput(BaseModel):
    default_execution_mode: Literal["ask", "autonomous"] = "autonomous"
    reasoning_effort: Literal['low','medium','high','xhigh','max'] = 'medium'
    model: str = "sonnet"
    max_turns: int | None = Field(default=40, ge=1)
    task_timeout_minutes: int = Field(default=20, ge=1, le=120)
    max_budget_usd: float | None = Field(default=None, gt=0, le=1000, allow_inf_nan=False)
    read_roots: list[str] = Field(default_factory=list, max_length=20)
    browser_enabled: bool = False
    desktop_enabled: bool = False
    capture_evidence: bool = True


def create_app(config, *, manager_factory=AgentManager, access_token=None):
    config.initialize()
    store = Store(config.data / "clara.sqlite3")
    from .skill_pack import seed_sources
    seed_sources(store)
    manager = manager_factory(config, store)
    from .portal import PortalWorker
    portal=PortalWorker(config,store,manager)
    token = access_token or secrets.token_urlsafe(32)
    cookie = secrets.token_urlsafe(32)
    origins = {f"http://127.0.0.1:{config.port}", f"http://localhost:{config.port}"}

    @asynccontextmanager
    async def lifespan(app):
        await manager.start()
        await portal.start()
        atomic_json(config.data / "dashboard.json", {"url": f"http://127.0.0.1:{config.port}/#access={token}"})
        try:
            yield
        finally:
            await portal.close()
            await manager.close()

    app = FastAPI(title="Clara Local Agent", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.manager, app.state.access_token = store, manager, token
    from .production_api import install_routes
    install_routes(app,config,store,manager)

    @app.middleware("http")
    async def local_access(request, call_next):
        host = request.headers.get("host", "")
        if host not in {f"127.0.0.1:{config.port}", f"localhost:{config.port}"}:
            return JSONResponse({"detail": "Clara accepts loopback requests only."}, status_code=403)
        if request.headers.get("origin") and request.headers["origin"] not in origins:
            return JSONResponse({"detail": "Request origin is not Clara's local dashboard."}, status_code=403)
        if request.url.path.startswith("/api/") and request.url.path != "/api/session":
            if not secrets.compare_digest(request.cookies.get("clara_session", ""), cookie):
                return JSONResponse({"detail": "Open Clara using its start/open command to connect this browser."}, status_code=401)
        if request.method not in {"GET", "HEAD"}:
            if request.headers.get("x-clara-request") != "1":
                return JSONResponse({"detail": "Missing local request header."}, status_code=403)
            try:
                size = int(request.headers.get("content-length", "-1"))
            except ValueError:
                size = -1
            if size < 0 or size > 26_000_000:
                return JSONResponse({"detail": "Request size must be known and below 26 MB."}, status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        return response

    @app.exception_handler(ValueError)
    async def bad_value(request, error):
        return JSONResponse({"detail": str(error)}, status_code=400)

    @app.get("/")
    async def index():
        return FileResponse(PACKAGE / "static" / "index.html")

    @app.get("/static/{name}")
    async def static(name: str):
        if name not in {"app.js", "production.js", "style.css"}:
            raise HTTPException(404)
        return FileResponse(PACKAGE / "static" / name)

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": __version__}

    @app.post("/api/session")
    async def session(request: Request):
        data = await request.json()
        supplied = data.get("token", "")
        if not isinstance(supplied, str) or not secrets.compare_digest(supplied, token):
            raise HTTPException(401, "Invalid dashboard access link. Run clara open.")
        response = JSONResponse({"connected": True})
        response.set_cookie("clara_session", cookie, httponly=True, samesite="strict", max_age=7 * 86400)
        return response

    @app.get("/api/status")
    async def status():
        return {"version": __version__, "auth": await auth_status(config), "connectors": connector_status(config),
                "desktop": desktop_ready(), "workspace": str(config.workspace),
                "active_job": manager.active_job, "queued": manager.queue.qsize(),
                "portal":{"running":bool(portal.task and not portal.task.done()),"error":portal.error,
                          "message":"Outbound assignment adapter; configure the existing portal protocol before enabling."}}

    @app.get("/api/settings")
    async def settings():
        return config.settings()

    @app.put("/api/settings")
    async def update_settings(settings: SettingsInput):
        if manager.active_job or not manager.queue.empty():
            raise ValueError("Finish or stop active tasks before changing tool access.")
        if settings.model not in {"sonnet", "opus", "haiku"}:
            raise ValueError("Choose sonnet, opus or haiku.")
        roots = []
        for value in settings.read_roots:
            path = Path(value).expanduser().resolve()
            if not path.is_dir():
                raise ValueError(f"Folder does not exist on this computer: {value}")
            roots.append(str(path))
        data = settings.model_dump()
        data["read_roots"] = sorted(set(roots))
        config.save_settings(data)
        return data

    @app.get("/api/conversations")
    async def conversations():
        return store.rows("SELECT * FROM conversations ORDER BY created DESC")

    @app.post("/api/conversations")
    async def create_conversation():
        return store.create_conversation()

    def require_conversation(cid):
        if not store.conversation(cid):
            raise HTTPException(404, "Conversation not found.")

    @app.get("/api/conversations/{cid}")
    async def conversation(cid: str):
        require_conversation(cid)
        jobs = store.rows("SELECT * FROM jobs WHERE conversation_id=? ORDER BY created", (cid,))
        return {"conversation": store.conversation(cid),
                "jobs": [{**job, "usage_report": job_usage(job)} for job in jobs],
                "usage_summary": conversation_usage(jobs),
                "files": store.rows("SELECT id,job_id,kind,name,size,created FROM files WHERE conversation_id=? ORDER BY created", (cid,)),
                "pending": manager.pending_requests(cid)}

    @app.get("/api/conversations/{cid}/usage.csv")
    async def export_usage(cid: str):
        require_conversation(cid)
        jobs = store.rows("SELECT * FROM jobs WHERE conversation_id=? ORDER BY created", (cid,))
        return Response(usage_csv(jobs), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="clara-task-usage.csv"'})

    @app.post("/api/conversations/{cid}/messages")
    async def message(cid: str, body: MessageInput):
        require_conversation(cid)
        mode = body.mode if body.mode is not None else config.settings()['default_execution_mode']
        if not body.text.strip() or mode not in {"ask", "autonomous"}:
            raise ValueError("Enter a task and choose a valid execution mode.")
        for fid in body.attachments:
            if not store.one("SELECT id FROM files WHERE id=? AND conversation_id=? AND kind='upload'", (fid, cid)):
                raise ValueError("An attachment does not belong to this conversation.")
        return manager.submit(cid, body.text.strip(), mode, body.attachments)

    @app.post("/api/jobs/{jid}/stop")
    async def stop(jid: str):
        if not store.job(jid):
            raise HTTPException(404)
        await manager.cancel(jid)
        return {"stopping": True}

    @app.get("/api/jobs/{jid}/diagnostics.json")
    async def export_diagnostics(jid: str):
        job = store.job(jid)
        if not job:
            raise HTTPException(404, "Task not found.")
        rows = store.rows("SELECT kind,data,created FROM events WHERE job_id=? AND kind != 'delta' ORDER BY id", (jid,))
        report = {"format_version": 1, "application_version": __version__,
                  "task": {key: job[key] for key in ("id", "prompt", "status", "created", "finished", "mode")},
                  "usage": job_usage(job),
                  "events": [{**row, "data": json.loads(row["data"])} for row in rows],
                  "coverage": "Local task history. Older tool outputs may be absent; excerpts may be truncated. "
                              "No screenshots or credential files are included. Task text can contain client information."}
        from .workflows import Workflows
        report['workflow']=Workflows(store,config).snapshot(job['conversation_id'])
        report['verification']=[{**row,'payload':json.loads(row['payload'])} for row in store.rows('SELECT * FROM evidence WHERE job_id=? AND kind!=?',(jid,'tool_observation'))]
        report['recovery']=store.one('SELECT * FROM execution_snapshots WHERE job_id=?',(jid,))
        report['screenshot_files']=store.rows("SELECT id,name,size FROM files WHERE job_id=? AND kind='evidence'",(jid,))
        return Response(json.dumps(report, indent=2, ensure_ascii=False), media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="clara-task-diagnostics.json"'})

    @app.post("/api/requests/{rid}")
    async def answer(rid: str, body: AnswerInput):
        manager.answer(rid, body.answer)
        return {"answered": True}

    @app.get("/api/conversations/{cid}/events")
    async def events(cid: str, request: Request, after: int = 0):
        require_conversation(cid)
        try:
            after = max(after, int(request.headers.get("last-event-id", "0")))
        except ValueError:
            raise HTTPException(400, "Invalid event cursor")
        async def stream():
            cursor = after
            ticks = 0
            while not await request.is_disconnected():
                rows = store.events(cid, cursor)
                for event in rows:
                    cursor = event["id"]
                    if event["kind"] == "usage":
                        event["data"] = normalize_usage(event["data"])
                    yield f"id: {cursor}\ndata: {json.dumps(event)}\n\n"
                if not rows:
                    ticks += 1
                    if ticks % 30 == 0:
                        yield ": keepalive\n\n"
                    await asyncio.sleep(0.3)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    @app.post("/api/conversations/{cid}/upload")
    async def upload(cid: str, file: UploadFile = File(...)):
        require_conversation(cid)
        data = await file.read(25_000_001)
        if len(data) > 25_000_000:
            raise ValueError("Attachments are limited to 25 MB each.")
        # Preserve a display name, but never use it to construct a filesystem path.
        name = Path((file.filename or "attachment").replace("\\", "/")).name[:180]
        fid = new_id()
        suffix = Path(name).suffix
        suffix = suffix if suffix.isascii() and suffix[1:].isalnum() and len(suffix) < 12 else ""
        target = config.data / "attachments" / (fid + suffix)
        target.write_bytes(data)
        store.execute("INSERT INTO files VALUES(?,?,NULL,?,?,?,?,?)", (fid, cid, "upload", name, str(target), len(data), time.time()))
        return {"id": fid, "name": name, "size": len(data)}

    @app.get("/api/files/{fid}")
    async def file(fid: str):
        item = store.one("SELECT * FROM files WHERE id=?", (fid,))
        if not item:
            raise HTTPException(404)
        path = Path(item["path"]).resolve()
        if not path.is_relative_to(config.data) or not path.is_file():
            raise HTTPException(404, "Attachment is no longer available.")
        return FileResponse(path, filename=item["name"], media_type="application/octet-stream")

    @app.get("/api/skills")
    async def skills():
        return list_skills(config)

    def editing_allowed():
        if manager.active_job or not manager.queue.empty():
            raise ValueError("Finish or stop active tasks before changing skills.")

    @app.put("/api/skills/{name}")
    async def skill(name: str, body: SkillInput):
        editing_allowed()
        return save_skill(config, name, body.content)

    @app.post("/api/skills/import")
    async def import_file(file: UploadFile = File(...)):
        editing_allowed()
        try:
            return import_skill(config, file.filename or "", await file.read(10_000_001))
        except (UnicodeError, __import__("zipfile").BadZipFile) as error:
            raise ValueError("Could not read this skill file. Use UTF-8 Markdown or a valid ZIP.") from error

    return app
