import asyncio
import base64
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from clara.portal_bindings import PortalBindings
from clara.portal_lease import LeaseLost
from clara.portal_preview import (KEY_FRAME_CAP, LIVE_INTERVAL_S, PROBE_INTERVAL_S, PreviewLoop, encode_frame,
                                  visible_action)
from clara.portal_transport import PortalRejected, PortalUnavailable
from test_portal_delivery import BASE, WORKER, setup


def picture(color=(40, 120, 90), size=(2560, 1440)):
    return Image.new('RGB', size, color)


def running_task(tmp_path):
    config, store, claim, lease = setup(tmp_path)
    jid = PortalBindings(store, BASE, WORKER).persist_claim(claim, 'Prepare this T1')['local_job_id']
    store.status(jid, 'running')
    return store, jid, lease.identity, store.job(jid)['conversation_id']


class Portal:
    """Answers clara-preview like the portal: wanted while a person watches."""
    def __init__(self, wanted=True):
        self.wanted, self.sent, self.fail = wanted, [], None
    async def request(self, operation, payload):
        assert operation == 'clara-preview'
        if self.fail:
            error, self.fail = self.fail, None
            raise error
        self.sent.append(payload)
        return SimpleNamespace(body={'accepted': True, 'wanted': self.wanted,
                                     'next_after_s': 2 if self.wanted else PROBE_INTERVAL_S, 'server_time': '2026-09-16T07:00:00Z'})


def loop_for(store, jid, identity, portal, clock, grab=picture):
    sleeps = []
    async def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds
    return PreviewLoop(store, portal, identity, jid, grab=grab, clock=lambda: clock[0], sleep=sleep), sleeps


def test_frames_are_scaled_jpegs_under_the_wire_cap_and_black_frames_are_dropped():
    encoded, width, height = encode_frame(picture())
    assert (width, height) == (1280, 720)
    raw = base64.b64decode(encoded)
    assert raw[:2] == b'\xff\xd8' and len(encoded) <= 400_000
    assert encode_frame(picture(color=(0, 0, 0))) is None, 'a locked or disconnected session draws nothing'
    assert encode_frame(picture(color=(8, 8, 8))) is None
    small = encode_frame(picture(size=(640, 400)))
    assert small[1:] == (640, 400), 'small desktops are not upscaled'


def test_live_frames_flow_only_while_someone_watches_and_probes_otherwise(tmp_path):
    store, jid, identity, _ = running_task(tmp_path)
    portal, clock = Portal(wanted=False), [100.0]
    loop, sleeps = loop_for(store, jid, identity, portal, clock)
    async def scenario():
        await loop._tick()                      # nobody watching yet: one probe, no image
        assert [p['kind'] for p in portal.sent] == ['probe'] and 'jpeg_base64' not in portal.sent[0]
        clock[0] += 3
        await loop._tick()                      # within the probe interval: silence
        assert len(portal.sent) == 1
        portal.wanted = True
        clock[0] += PROBE_INTERVAL_S
        await loop._tick()                      # probe learns that a person opened the card
        assert portal.sent[-1]['kind'] == 'probe' and loop.wanted is True
        clock[0] += LIVE_INTERVAL_S
        await loop._tick()
        frame = portal.sent[-1]
        assert frame['kind'] == 'live' and frame['width'] == 1280 and frame['seq'] == 3
        assert frame['captured_at'].endswith('Z') and frame['job_id'] == identity.job_id
        clock[0] += 1
        await loop._tick()                      # not yet 2 s: no second live frame
        assert len(portal.sent) == 3
        portal.wanted = False
        clock[0] += LIVE_INTERVAL_S
        await loop._tick()                      # the reply says the viewer left
        assert portal.sent[-1]['kind'] == 'live' and loop.wanted is False
        clock[0] += LIVE_INTERVAL_S
        await loop._tick()
        assert portal.sent[-1]['kind'] == 'live', 'the last live reply had already flipped wanted off; a probe follows later'
    asyncio.run(scenario())


def test_key_frames_follow_visible_actions_regardless_of_watching_with_a_cap(tmp_path):
    store, jid, identity, cid = running_task(tmp_path)
    portal, clock = Portal(wanted=False), [100.0]
    screen = [(40, 120, 90)]
    loop, _ = loop_for(store, jid, identity, portal, clock, grab=lambda: picture(color=screen[0]))
    async def scenario():
        await loop._tick()
        store.event(cid, jid, 'tool', {'id': 't1', 'name': 'mcp__windows__Screenshot', 'input': '{}'})   # read-only: no frame
        store.event(cid, jid, 'tool', {'id': 't2', 'name': 'mcp__windows__Click', 'input': '{"x": 1}'})
        store.event(cid, jid, 'tool_done', {'id': 't2', 'name': 'mcp__windows__Click'})
        store.event(cid, jid, 'checkpoint', {'stage': 'documents', 'status': 'verified'})
        clock[0] += LIVE_INTERVAL_S
        await loop._tick()
        keys = [p for p in portal.sent if p['kind'] == 'key']
        # Actions that land in one tick share one grab, attributed to the last of them.
        assert [k['label'] for k in keys] == ['Saved progress: documents'] and keys[0]['stage'] == 'documents'
        assert keys[0]['activity_event_uid'].startswith('local-') and 'jpeg_base64' in keys[0]
        store.event(cid, jid, 'tool', {'id': 't3', 'name': 'mcp__windows__Type', 'input': '{}'})
        clock[0] += LIVE_INTERVAL_S
        await loop._tick()
        assert len([p for p in portal.sent if p['kind'] == 'key']) == 1, 'an unchanged screen earns no second key frame'
        screen[0] = (200, 30, 30)
        store.event(cid, jid, 'tool', {'id': 't4', 'name': 'mcp__windows__Type', 'input': '{}'})
        clock[0] += LIVE_INTERVAL_S
        await loop._tick()
        keys = [p for p in portal.sent if p['kind'] == 'key']
        assert [k['label'] for k in keys] == ['Saved progress: documents', 'Type']
        loop.key_frames = KEY_FRAME_CAP
        screen[0] = (30, 30, 200)
        store.event(cid, jid, 'tool', {'id': 't5', 'name': 'mcp__chrome__click', 'input': '{}'})
        clock[0] += LIVE_INTERVAL_S
        await loop._tick()
        assert len([p for p in portal.sent if p['kind'] == 'key']) == 2, 'beyond the cap ordinary actions earn no frame'
        store.event(cid, jid, 'checkpoint', {'stage': 'delivery', 'status': 'verified'})
        clock[0] += LIVE_INTERVAL_S
        await loop._tick()
        keys = [p for p in portal.sent if p['kind'] == 'key']
        assert keys[-1]['label'] == 'Saved progress: delivery', 'checkpoints still earn a frame beyond the cap'
    asyncio.run(scenario())


def test_one_grab_per_tick_serves_both_the_key_frame_and_the_live_frame(tmp_path):
    store, jid, identity, cid = running_task(tmp_path)
    portal, clock = Portal(wanted=True), [100.0]
    grabs = []
    def grab():
        grabs.append(1)
        return picture()
    loop, _ = loop_for(store, jid, identity, portal, clock, grab=grab)
    async def scenario():
        await loop._tick()                      # probe: learns that someone watches
        store.event(cid, jid, 'tool', {'id': 't1', 'name': 'mcp__windows__Click', 'input': '{}'})
        clock[0] += LIVE_INTERVAL_S
        await loop._tick()
        assert [p['kind'] for p in portal.sent] == ['probe', 'key', 'live'] and len(grabs) == 1
        assert portal.sent[1]['jpeg_base64'] == portal.sent[2]['jpeg_base64']
    asyncio.run(scenario())


def test_failed_captures_back_off_while_probes_keep_the_watch_fresh(tmp_path):
    store, jid, identity, cid = running_task(tmp_path)
    portal, clock = Portal(wanted=True), [100.0]
    grabs = []
    def grab():
        grabs.append(clock[0])
        return None                            # a disconnected session: Windows draws nothing
    loop, _ = loop_for(store, jid, identity, portal, clock, grab=grab)
    async def scenario():
        await loop._tick()                      # probe only
        clock[0] += LIVE_INTERVAL_S
        await loop._tick()                      # first grab fails: captures blocked for 10 s
        assert len(grabs) == 1 and loop.capture_blocked_until == clock[0] + PROBE_INTERVAL_S
        for _ in range(4):
            clock[0] += LIVE_INTERVAL_S
            store.event(cid, jid, 'tool', {'id': 'x' + str(clock[0]), 'name': 'mcp__windows__Click', 'input': '{}'})
            await loop._tick()
        assert len(grabs) == 1, 'no grab while blocked, not even for key frames'
        clock[0] += LIVE_INTERVAL_S
        await loop._tick()                      # 10 s later: one more try, then 20 s
        assert len(grabs) == 2 and loop.capture_blocked_until == clock[0] + 2 * PROBE_INTERVAL_S
        for _ in range(12):
            clock[0] += LIVE_INTERVAL_S
            await loop._tick()
        assert len(grabs) == 3 and loop.blank_failures == 3
        assert all(p['kind'] == 'probe' for p in portal.sent) and len(portal.sent) >= 3, 'probes continued throughout'
        # The screen comes back: the next allowed grab succeeds and the backoff resets.
        loop.grab = picture
        clock[0] += 3 * PROBE_INTERVAL_S
        await loop._tick()
        assert portal.sent[-1]['kind'] == 'live' and loop.blank_failures == 0 and loop.capture_blocked_until is None
    asyncio.run(scenario())


def test_run_cycles_ticks_with_the_live_interval_and_resets_backoff_after_success(tmp_path):
    store, jid, identity, _ = running_task(tmp_path)
    portal, clock = Portal(wanted=True), [100.0]
    loop, sleeps = loop_for(store, jid, identity, portal, clock)
    ticks = []
    original = loop._tick
    async def tick():
        ticks.append(1)
        n = len(ticks)
        if n in {2, 3}:
            raise RuntimeError('grab exploded')
        if n == 5:
            store.status(jid, 'completed')
        return await original()
    loop._tick = tick
    asyncio.run(loop.run())
    # tick 1 ok → 2 s; failures → 2, 4; tick 4 ok resets the backoff → 2 s; tick 5 ends the task.
    assert sleeps == [LIVE_INTERVAL_S, 2, 4, LIVE_INTERVAL_S] and loop.backoff == 0
    loop2, sleeps2 = loop_for(store, jid, identity, portal, clock)
    store.status(jid, 'running')
    count = []
    async def always_fail():
        count.append(1)
        if len(count) > 6:
            store.status(jid, 'failed')
            return 'failed'
        raise RuntimeError('still broken')
    loop2._tick = always_fail
    asyncio.run(loop2.run())
    assert sleeps2 == [2, 4, 8, 16, 30, 30], 'the backoff ceiling is 30 s'


def test_desktop_capture_is_windows_only(monkeypatch):
    from clara import portal_preview
    monkeypatch.setattr(portal_preview.os, 'name', 'posix')
    assert portal_preview.grab_desktop() is None


def test_visible_action_classification():
    assert visible_action('tool', {'name': 'mcp__windows__Type'}) == (True, 'Type', 'Type')
    assert visible_action('tool', {'name': 'mcp__chrome__navigate_page'})[0] is True
    assert visible_action('tool', {'name': 'mcp__chrome__take_snapshot'})[0] is False
    assert visible_action('tool', {'name': 'mcp__clara__save_checkpoint'})[0] is False
    assert visible_action('tool_done', {'name': 'mcp__windows__Click'})[0] is False
    assert visible_action('checkpoint', {})[1:] == ('save_checkpoint', 'Saved progress')


def test_a_pause_for_a_question_sends_one_final_frame_and_the_end_of_the_task_stops_the_loop(tmp_path):
    store, jid, identity, _ = running_task(tmp_path)
    portal, clock = Portal(wanted=True), [100.0]
    loop, sleeps = loop_for(store, jid, identity, portal, clock)
    async def scenario():
        await loop._tick()                      # the first call is always a probe: she learns someone watches
        clock[0] += LIVE_INTERVAL_S
        await loop._tick()
        assert [p['kind'] for p in portal.sent] == ['probe', 'live']
        store.status(jid, 'waiting')
        await loop._tick()
        await loop._tick()
        assert [p['kind'] for p in portal.sent] == ['probe', 'live', 'live'], 'exactly one final frame while she waits'
        store.status(jid, 'running')
        clock[0] += LIVE_INTERVAL_S
        await loop._tick()
        assert len(portal.sent) == 4
        store.status(jid, 'needs_review')
        await loop.run()                        # returns on its own once the task is over
        assert len(portal.sent) == 4 and sleeps == []
    asyncio.run(scenario())


def test_failures_back_off_and_never_raise_out_of_the_loop(tmp_path):
    store, jid, identity, _ = running_task(tmp_path)
    portal, clock = Portal(wanted=True), [100.0]
    loop, sleeps = loop_for(store, jid, identity, portal, clock)
    ticks = []
    original = loop._tick
    async def tick():
        ticks.append(1)
        if len(ticks) == 1:
            raise RuntimeError('JPEG encoder exploded')
        if len(ticks) == 2:
            raise PortalRejected('invalid_request', 400)
        if len(ticks) == 3:
            raise PortalUnavailable('portal has no clara-preview yet')
        if len(ticks) == 4:
            raise PortalRejected('fenced', 409)
        return await original()
    loop._tick = tick
    asyncio.run(loop.run())
    assert ticks == [1, 1, 1, 1], 'a fenced reply ends the loop; earlier failures only delayed it'
    assert sleeps == [2, 4, 60]
    assert portal.sent == []


def test_lost_lease_and_cancellation_propagate(tmp_path):
    store, jid, identity, _ = running_task(tmp_path)
    portal, clock = Portal(wanted=True), [100.0]
    loop, _ = loop_for(store, jid, identity, portal, clock)
    async def tick():
        raise LeaseLost('gone')
    loop._tick = tick
    with pytest.raises(LeaseLost):
        asyncio.run(loop.run())


def test_a_disconnected_session_sends_no_frame_but_keeps_probing(tmp_path):
    store, jid, identity, _ = running_task(tmp_path)
    portal, clock = Portal(wanted=True), [100.0]
    loop, _ = loop_for(store, jid, identity, portal, clock, grab=lambda: None)
    async def scenario():
        await loop._tick()
        assert [p['kind'] for p in portal.sent] == ['probe'], 'nothing rendered: a probe keeps the watch state fresh'
        clock[0] += LIVE_INTERVAL_S
        await loop._tick()
        assert len(portal.sent) == 1, 'probes stay on the probe interval even while wanted'
    asyncio.run(scenario())
