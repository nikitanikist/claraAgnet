"""Live desktop frames for the portal while a task runs.

Frames are captured inside the worker process (Pillow), never by launching a
helper: a helper process would be counted as Clara's own unfinished work by the
end-of-task observer. The loop is isolated from the session's control loops:
no capture, encode or upload failure can stop or cancel a task; it backs off
and tries again. It captures live frames only while the portal says someone is
watching, sends a frame-less probe otherwise, and keeps one key frame per
visible action so a run can be replayed afterwards. It stops on its own when
the task is no longer running.
"""
import asyncio
import base64
import ctypes
import hashlib
import io
import json
import os
import time
from dataclasses import asdict
from datetime import datetime, timezone

from .portal_lease import LeaseLost
from .portal_transport import PortalRejected, PortalUnavailable

LIVE_INTERVAL_S = 2
PROBE_INTERVAL_S = 10
MAX_BACKOFF_S = 30
UNAVAILABLE_BACKOFF_S = 60
FRAME_WIDTH = 1280
JPEG_QUALITY = 62
MAX_BASE64 = 400_000
KEY_FRAME_CAP = 120
BLACK_LEVEL = 12

# Tools whose start changes something on screen; each of these earns a key frame.
READONLY_TOOLS = {'take_snapshot', 'take_screenshot', 'list_pages', 'Snapshot', 'Screenshot', 'ListWindows',
                  'InspectControls', 'ApplicationInfo', 'VerifyWindow'}
ACTIVE_STATUSES = {'running', 'cancelling'}


def _dpi_aware():
    """Ask Windows for physical pixels once, so frames are neither cropped nor scaled."""
    if os.name != 'nt':
        return
    try:
        ctypes.WinDLL('shcore').SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.WinDLL('user32').SetProcessDPIAware()
        except Exception:
            pass


def grab_desktop():
    """The whole desktop as a Pillow image, or None when Windows draws nothing (locked or disconnected)."""
    if os.name != 'nt':
        return None  # only the dedicated Windows desktop is ever captured
    from PIL import ImageGrab
    try:
        image = ImageGrab.grab(all_screens=True)
    except Exception:
        return None
    if image is None or image.width < 2 or image.height < 2:
        return None
    return image


def encode_frame(image, width=FRAME_WIDTH, quality=JPEG_QUALITY):
    """(base64 JPEG, width, height) or None for a black frame or an oversized encoding."""
    from PIL import Image
    if image.mode not in {'RGB', 'L'}:
        image = image.convert('RGB')
    extrema = image.convert('L').getextrema()
    if extrema[1] < BLACK_LEVEL:
        return None  # nothing rendered: locked, disconnected, or a blank desktop
    if image.width > width:
        height = max(1, round(image.height * width / image.width))
        image = image.resize((width, height), Image.LANCZOS)
    for q in (quality, 45, 30):
        buffer = io.BytesIO()
        image.convert('RGB').save(buffer, format='JPEG', quality=q, optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
        if len(encoded) <= MAX_BASE64:
            return encoded, image.width, image.height
    return None


def visible_action(kind, data):
    """Whether a local event is an action worth a key frame, and its (tool, label)."""
    if kind == 'checkpoint':
        stage = str(data.get('stage', ''))[:64]
        return True, 'save_checkpoint', ('Saved progress: ' + stage if stage else 'Saved progress')[:120]
    if kind != 'tool':
        return False, None, None
    full = str(data.get('name', ''))
    leaf = full.rsplit('__', 1)[-1]
    if not full.startswith(('mcp__windows__', 'mcp__chrome__')) or leaf in READONLY_TOOLS:
        return False, None, None
    return True, leaf[:64], leaf[:120]


class PreviewLoop:
    """One background task per portal attempt; see the module docstring."""

    def __init__(self, store, transport, identity, local_job_id, *, grab=grab_desktop, encode=encode_frame,
                 clock=time.monotonic, sleep=asyncio.sleep, now=None):
        self.store, self.transport, self.identity, self.local_job_id = store, transport, identity, local_job_id
        self.grab, self.encode, self.clock, self.sleep = grab, encode, clock, sleep
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.seq = 0
        self.wanted = False
        self.next_after = PROBE_INTERVAL_S
        self.last_live = self.last_probe = None
        self.backoff = 0
        self.key_frames = 0
        self.after_event = self._latest_event_id()
        self.sent = 0
        self.final_sent = False
        self.stopped = False
        # A session that draws nothing (locked, disconnected) fails or blanks every
        # grab; each failed Windows grab also leaks a screen-sized bitmap inside
        # Pillow. Failed captures therefore back off on their own, up to 30 s,
        # while probes keep the watch state fresh.
        self.blank_failures = 0
        self.capture_blocked_until = None
        self.last_key_digest = None

    def _latest_event_id(self):
        row = self.store.one('SELECT max(id) AS id FROM events WHERE job_id=?', (self.local_job_id,))
        return int(row['id']) if row and row['id'] is not None else 0

    def _status(self):
        job = self.store.job(self.local_job_id)
        return job['status'] if job else None

    def _new_actions(self):
        rows = self.store.rows("SELECT id,kind,data FROM events WHERE job_id=? AND id>? AND kind IN ('tool','checkpoint') ORDER BY id LIMIT 50",
                               (self.local_job_id, self.after_event))
        actions = []
        for row in rows:
            self.after_event = max(self.after_event, int(row['id']))
            try:
                data = json.loads(row['data'])
            except (TypeError, ValueError):
                continue
            ok, tool, label = visible_action(row['kind'], data)
            if ok:
                actions.append(('local-' + str(row['id']), tool, label, data.get('stage')))
        return actions

    def _capture_allowed(self):
        return self.capture_blocked_until is None or self.clock() >= self.capture_blocked_until

    async def _capture(self):
        if not self._capture_allowed():
            return None
        image = await asyncio.to_thread(self.grab)
        frame = await asyncio.to_thread(self.encode, image) if image is not None else None
        if frame is None:
            self.blank_failures += 1
            wait = min(MAX_BACKOFF_S, PROBE_INTERVAL_S * 2 ** (self.blank_failures - 1))
            self.capture_blocked_until = self.clock() + wait
            return None
        self.blank_failures, self.capture_blocked_until = 0, None
        return frame

    async def _send(self, kind, frame=None, *, event_uid=None, stage=None, label=None):
        self.seq += 1
        payload = {**asdict(self.identity), 'seq': self.seq, 'kind': kind,
                   'captured_at': self.now().isoformat().replace('+00:00', 'Z')}
        if frame is not None:
            encoded, width, height = frame
            payload.update(width=width, height=height, jpeg_base64=encoded)
        if event_uid is not None:
            payload['activity_event_uid'] = str(event_uid)[:80]
        if stage:
            payload['stage'] = str(stage)[:64]
        if label:
            payload['label'] = str(label)[:120]
        reply = await self.transport.request('clara-preview', payload)
        body = reply.body
        self.wanted = bool(body.get('wanted'))
        self.next_after = max(1, min(3600, int(body.get('next_after_s', PROBE_INTERVAL_S))))
        self.backoff = 0
        self.sent += 1
        return body

    async def _tick(self):
        status = self._status()
        if status not in ACTIVE_STATUSES:
            if status == 'waiting' and not self.final_sent:
                # One last look while she waits for a person; nothing more until she resumes.
                frame = await self._capture()
                if frame is not None:
                    await self._send('live', frame)
                self.final_sent = True
            return status
        self.final_sent = False
        now = self.clock()
        # One grab per tick serves both purposes. Actions that landed in the same
        # tick share that grab: the frame shows the screen right after the last
        # of them, and is attributed to that last action (a best-effort replay,
        # never a claim to show every intermediate state).
        actions = [a for a in self._new_actions()
                   if self.key_frames < KEY_FRAME_CAP or a[1] == 'save_checkpoint']
        live_due = self.wanted and (self.last_live is None or now - self.last_live >= LIVE_INTERVAL_S)
        frame = await self._capture() if (actions or live_due) else None
        if actions and frame is not None:
            digest = hashlib.sha1(frame[0].encode('ascii')).hexdigest()
            if digest != self.last_key_digest:  # an unchanged screen earns no second key frame
                event_uid, tool, label, stage = actions[-1]
                await self._send('key', frame, event_uid=event_uid, stage=stage, label=label)
                self.key_frames += 1
                self.last_key_digest = digest
        if live_due:
            self.last_live = now
            if frame is not None:
                await self._send('live', frame)
            elif self.last_probe is None or now - self.last_probe >= PROBE_INTERVAL_S:
                # Nothing rendered (locked or disconnected session): keep the
                # watch fresh at the slow cadence instead of every 2 s.
                self.last_probe = now
                await self._send('probe')
        elif not self.wanted and (self.last_probe is None or now - self.last_probe >= self.next_after):
            self.last_probe = now
            await self._send('probe')
        return status

    async def run(self):
        _dpi_aware()
        while not self.stopped:
            try:
                status = await self._tick()
                if status is None or status not in ACTIVE_STATUSES | {'waiting', 'queued'}:
                    return  # the task ended; the end-of-task observer must see a quiet worker
                delay = LIVE_INTERVAL_S
            except (LeaseLost, asyncio.CancelledError):
                raise
            except PortalRejected as error:
                if error.code in {'fenced', 'lease_expired', 'unauthorized', 'forbidden'}:
                    return  # permission is gone; the control loops handle the task itself
                self.backoff = min(MAX_BACKOFF_S, max(LIVE_INTERVAL_S, self.backoff * 2))
                delay = self.backoff
            except PortalUnavailable:
                delay = UNAVAILABLE_BACKOFF_S  # a portal without this function yet, or a network gap
            except Exception:
                self.backoff = min(MAX_BACKOFF_S, max(LIVE_INTERVAL_S, self.backoff * 2))
                delay = self.backoff
            await self.sleep(delay)

    def stop(self):
        self.stopped = True
