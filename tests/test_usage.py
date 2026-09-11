import asyncio
import csv
import io
import json

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock
from fastapi.testclient import TestClient

from clara.agent import AgentManager
from clara.app import create_app
from clara.config import Config
from clara.store import Store
from clara.usage import UsageTracker, normalize_usage, conversation_usage


def result(**kwargs):
    return ResultMessage(**{"subtype": "success", "duration_ms": 800, "duration_api_ms": 600,
                            "is_error": False, "num_turns": 3, "session_id": "test", **kwargs})


def model_usage(input=100, output=20, cached=300, written=50, cost=0.02):
    return {"inputTokens": input, "outputTokens": output, "cacheReadInputTokens": cached,
            "cacheCreationInputTokens": written, "costUSD": cost}


def test_result_includes_all_models_without_double_counting_main_usage():
    report = UsageTracker().result(result(usage={"input_tokens": 100, "output_tokens": 20},
        total_cost_usd=0.03, model_usage={"main": model_usage(), "helper": model_usage(10, 2, 30, 5, 0.01)}), 900)
    assert report["total_tokens"] == 517
    assert report["tokens"] == {"input_tokens": 110, "output_tokens": 22,
                                "cache_read_input_tokens": 330, "cache_creation_input_tokens": 55}
    assert report["scope"] == "all_models"
    assert report["sdk_estimated_usd"] == 0.03
    assert report["wall_duration_ms"] == 900


def test_independent_followup_costs_are_summed_once():
    tracker = UsageTracker()
    jobs = [{"status": "completed", "usage": tracker.result(result(total_cost_usd=cost,
             usage={"input_tokens": tokens, "output_tokens": 5}), 900)} for cost, tokens in [(0.04, 10), (0.01, 20)]]
    summary = conversation_usage(jobs)
    assert summary["sdk_estimated_usd"] == 0.05
    assert summary["total_tokens"] == 40
    assert summary["tasks"] == 2


def test_partial_usage_deduplicates_and_never_uses_placeholder_output():
    tracker = UsageTracker()
    for _ in range(2):
        tracker.observe(AssistantMessage(content=[TextBlock(text="Working")], model="test", message_id="same",
            usage={"input_tokens": 15, "output_tokens": 1, "cache_read_input_tokens": 100}))
    tracker.observe(AssistantMessage(content=[], model="test", message_id="child", parent_tool_use_id="parent",
                                     usage={"input_tokens": 300, "output_tokens": 1}))
    report = tracker.partial(1000)
    assert report["tokens"]["input_tokens"] == 15
    assert report["tokens"]["cache_read_input_tokens"] == 100
    assert report["tokens"]["output_tokens"] is None
    assert report["total_tokens"] is None
    assert report["sdk_estimated_usd"] is None
    assert report["coverage"] == "partial"
    crash = tracker.result(result(subtype="error_during_execution", is_error=True,
                                  total_cost_usd=0, usage={"input_tokens": 0, "output_tokens": 0}), 1000)
    assert crash == report


def test_missing_usage_is_unknown_and_known_zero_remains_zero():
    missing = normalize_usage(None)
    assert missing["total_tokens"] is None and missing["sdk_estimated_usd"] is None
    zero = normalize_usage({"tokens": {"input_tokens": 0, "output_tokens": 0}, "sdk_estimated_usd": 0})
    assert zero["total_tokens"] == 0 and zero["sdk_estimated_usd"] == 0
    old = normalize_usage(json.dumps({"tokens": {"input_tokens": 3, "output_tokens": 2}, "sdk_estimated_usd": .01}))
    assert old["total_tokens"] == 5
    summary = conversation_usage([{"status": "completed", "usage": zero}, {"status": "cancelled", "usage": None}])
    assert summary["token_tasks"] == 1 and summary["incomplete_tasks"] == 1


def test_unknown_model_price_is_not_reported_as_free():
    model = {**model_usage(cost=0), "costBasis": "unknown"}
    report = UsageTracker().result(result(model_usage={"new-model": model}, total_cost_usd=0), 100)
    assert report["unknown_price"]
    assert report["total_tokens"] == 470
    assert report["sdk_estimated_usd"] is None
    assert report["models"][0]["sdk_estimated_usd"] is None


def test_model_costs_can_supply_a_missing_result_estimate():
    report = UsageTracker().result(result(model_usage={"main": model_usage(cost=.02),
                                                       "helper": model_usage(cost=.01)}), 100)
    assert report["sdk_estimated_usd"] == .03


def test_budget_error_uses_whole_model_usage_including_crossing_step():
    report = UsageTracker().result(result(subtype="error_max_budget_usd", is_error=True,
        usage={"input_tokens": 10, "output_tokens": 1}, model_usage={"main": model_usage(cost=.07)}, total_cost_usd=.07), 1000, .05)
    assert report["total_tokens"] == 470 and report["sdk_estimated_usd"] == .07
    assert report["limit_usd"] == .05 and report["coverage"] == "reported"


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
def test_runtime_interruption_persists_partial_usage(tmp_path, monkeypatch, failure):
    class SDKDouble:
        def __init__(self, options): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def query(self, prompt): pass
        async def receive_response(self):
            yield AssistantMessage(content=[], model="test", message_id="step", usage={"input_tokens": 17, "output_tokens": 1})
            raise failure("test stop")
    async def auth(): return {"connected": True, "plan": "max"}
    monkeypatch.setattr("clara.agent.ClaudeSDKClient", SDKDouble)
    monkeypatch.setattr("clara.agent.auth_status", auth)
    cfg = Config(tmp_path); cfg.initialize(); store = Store(tmp_path / "db")
    job = store.create_job(store.create_conversation()["id"], "test", "ask", [])
    with pytest.raises(failure):
        asyncio.run(AgentManager(cfg, store).execute(job))
    report = json.loads(store.job(job["id"])["usage"])
    assert report["coverage"] == "partial" and report["tokens"]["input_tokens"] == 17
    assert report["sdk_estimated_usd"] is None
    assert len([e for e in store.events(job["conversation_id"]) if e["kind"] == "usage"]) == 1


def test_csv_export_and_api_preserve_unknowns_and_reject_invalid_budget(tmp_path):
    class Manager:
        active_job = None
        queue = asyncio.Queue()
        def __init__(self, *args): pass
        async def start(self): pass
        async def close(self): pass
        def pending_requests(self, cid): return []
    app = create_app(Config(tmp_path), manager_factory=Manager, access_token="test-only")
    store = app.state.store
    cid = store.create_conversation()["id"]
    job = store.create_job(cid, '=HYPERLINK("https://example.test")', "ask", [])
    store.status(job["id"], "cancelled")
    with TestClient(app, base_url="http://127.0.0.1:8876") as client:
        assert client.get(f"/api/conversations/{cid}/usage.csv").status_code == 401
        client.headers["x-clara-request"] = "1"
        assert client.post("/api/session", json={"token": "test-only"}).status_code == 200
        data = client.get(f"/api/conversations/{cid}").json()
        assert data["jobs"][0]["usage_report"]["total_tokens"] is None
        assert data["usage_summary"]["cost_tasks"] == 0
        response = client.get(f"/api/conversations/{cid}/usage.csv")
        rows = list(csv.DictReader(io.StringIO(response.text.lstrip("\ufeff"))))
        assert rows[0]["Task"].startswith("'=HYPERLINK")
        assert rows[0]["SDK API estimate USD"] == ""
        assert rows[0]["Total tokens"] == ""
        for invalid in [-1, 0, 1001, "NaN", "Infinity"]:
            assert client.put("/api/settings", json={"max_budget_usd": invalid}).status_code == 422
        assert client.put("/api/settings", json={"max_budget_usd": 0.05}).status_code == 200
        assert client.get("/api/settings").json()["max_budget_usd"] == .05
        assert client.put("/api/settings", json={"max_budget_usd": None}).status_code == 200
