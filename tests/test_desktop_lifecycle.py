from clara.desktop_lifecycle import DesktopLifecycle


def test_cleanup_review_excludes_preexisting_and_closed_windows_and_runs_once():
    windows = {"original:1": "User window"}
    tracker = DesktopLifecycle(lambda: dict(windows))
    tracker.begin_action("open")
    windows["temporary:1"] = "Agent search"
    windows["closed:1"] = "Already closed"
    tracker.end_action("open")
    del windows["closed:1"]
    review = tracker.stop_check({})
    assert review["decision"] == "block"
    assert "temporary:1" in review["reason"]
    assert "original:1" not in review["reason"] and "closed:1" not in review["reason"]
    assert "Preserve user-owned windows" in review["reason"]
    assert tracker.stop_check({}) == {}


def test_no_cleanup_round_for_direct_file_tasks_or_failed_observation():
    calls = []
    tracker = DesktopLifecycle(lambda: calls.append(1) or {})
    assert tracker.stop_check({}) == {}
    assert not calls
    tracker.begin_action("read")
    tracker.end_action("read")
    assert tracker.stop_check({}) == {}
    def inaccessible(): raise OSError("locked")
    tracker = DesktopLifecycle(inaccessible)
    tracker.begin_action("open")
    tracker.end_action("open")
    assert tracker.stop_check({}) == {}


def test_stop_hook_does_not_loop_or_close_windows_itself():
    windows = {}
    tracker = DesktopLifecycle(lambda: dict(windows))
    tracker.begin_action("open")
    windows["test:1"] = "Review this output"
    tracker.end_action("open")
    assert tracker.stop_check({"stop_hook_active": True}) == {}
    assert windows == {"test:1": "Review this output"}
    assert tracker.stop_check({})["decision"] == "block"
    assert windows == {"test:1": "Review this output"}
