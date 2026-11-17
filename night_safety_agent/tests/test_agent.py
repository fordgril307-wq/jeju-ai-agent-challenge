"""재현성 테스트 — 지수·등급·순찰 권고·반출 검사·라우터·LLM 도구 호출 루프.

실행: python -m pytest -q
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import core, router  # noqa: E402
from tools import safety  # noqa: E402
from tools.registry import resolve_period, run_tool, today  # noqa: E402


def test_grade_cuts():
    assert safety.grade_of(119.9) == 0
    assert safety.grade_of(120) == 1
    assert safety.grade_of(140) == 2
    assert safety.grade_of(170) == 3


def test_forecast_shape_and_reproducible():
    a = safety.forecast_safety("제주시", "2026-11-18", 3)
    b = safety.forecast_safety("제주시", "2026-11-18", 3)
    assert a.ok and len(a.data) == 26 * 3
    pd.testing.assert_frame_equal(a.data, b.data)
    assert (a.data.하한 <= a.data.예보_밤인원).all() and (a.data.예보_밤인원 <= a.data.상한).all()


def test_event_raises_index():
    base = safety.forecast_safety("삼도2동", "2026-11-20", 1)
    ev = safety.forecast_safety("삼도2동", "2026-11-20", 1, {"events": [{"date": "2026-11-20", "emd": "삼도2동", "name": "t", "uplift": 0.5}]})
    assert ev.data.지수.iloc[0] > base.data.지수.iloc[0]


def test_backtest_reports_both_errors():
    r = safety.backtest("전체")
    assert {"mape_model", "mape_baseline", "adopted"} <= set(r.extra)


def test_patrol_counts():
    f = pd.DataFrame([
        {"날짜": "2026-11-21", "요일": "토", "권역": "서부", "읍면동": "A", "등급": 3, "지수": 175, "예보_밤인원": 100, "21~24시": 60, "0~3시": 40, "요인": ""},
        {"날짜": "2026-11-21", "요일": "토", "권역": "서부", "읍면동": "B", "등급": 2, "지수": 150, "예보_밤인원": 100, "21~24시": 60, "0~3시": 40, "요인": ""},
        {"날짜": "2026-11-21", "요일": "토", "권역": "동부", "읍면동": "C", "등급": 0, "지수": 100, "예보_밤인원": 100, "21~24시": 60, "0~3시": 40, "요인": ""},
    ])
    r = safety.plan_patrol(f)
    assert r.extra["total_extra"] == 3 and len(r.data) == 2


def test_export_masks_small_counts_and_personal_cols():
    t = pd.DataFrame({"읍면동": ["A", "B"], "예보_밤인원": [5, 50], "국적": ["x", "y"]})
    r = safety.check_export(t)
    assert "국적" not in r.data.columns
    assert r.data.예보_밤인원.iloc[0] == "10 미만"


def test_fact_check_unknown_claim():
    r = safety.fact_check("제주 바다에 상어가 많다던데")
    assert r.extra["verdict"] == "확인 안 됨"


def test_router_intents():
    assert router.parse("다음 주 밤 순찰 어디부터?")["clarify"] is True
    assert router.parse("제주시 이번 주말 순찰")["args"]["region"] == "제주시"
    assert router.parse("제주 범죄율 1위 진짜야?")["intent"] == "fact"
    assert router.parse("삼도2동에 가로등 300개 추가하면?")["intent"] == "simulate"
    assert router.parse("가로등 더 달 곳 TOP 5")["args"]["top"] == "5"


def test_period():
    s, d = resolve_period("다음 주")
    assert pd.to_datetime(s).dayofweek == 0 and d == 7
    assert resolve_period(None)[0] == today().isoformat()


def test_rule_mode_full_flow():
    st = {}
    t = core.run("이번 주말 제주시 밤 순찰 어디부터?", st, use_llm=False)
    assert {"forecast", "backtest", "patrol", "report"} <= set(st)
    assert all(s.status != "✗" for s in t.steps)


def test_llm_loop_with_fake_model(monkeypatch):
    """LLM이 도구를 고르고 결과로 답을 쓰는 루프 확인 (가짜 모델)."""
    class Fake:
        label = "fake:model"
        def __init__(self, system): self.n = 0
        def user(self, text): pass
        def step(self):
            self.n += 1
            if self.n == 1:
                return "tools", [("c1", "forecast_safety", {"region": "제주시", "period": "이번 주말"})]
            if self.n == 2:
                return "tools", [("c2", "plan_patrol", {})]
            return "text", "삼도2동 토요일 3단계, 추가 순찰 권고."
        def tool_results(self, r): self.last = r

    import agent.llm as llm_mod
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(llm_mod, "LLM", Fake)
    st = {}
    t = core.run("이번 주말 제주시 순찰 어디부터?", st, use_llm=True)
    assert t.mode == "fake:model" and "patrol" in st and t.answer.startswith("삼도2동")


def test_llm_failure_falls_back_to_rules(monkeypatch):
    import agent.llm as llm_mod
    class Broken:
        def __init__(self, system): raise ConnectionError("offline")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(llm_mod, "LLM", Broken)
    st = {}
    t = core.run("가로등 더 달 곳 TOP 3", st, use_llm=True)
    assert any(s.status == "!" and "우회" in s.detail for s in t.steps) and "blind" in st


def test_simulate_tool():
    st = {}
    r = run_tool("simulate", {"region": "제주시", "event_emd": "탑동", "event_date": "2026-11-20", "event_uplift": "0.5"}, st)
    assert r.ok and len(r.data) >= 1 and r.data.변화.iloc[0] > 0
