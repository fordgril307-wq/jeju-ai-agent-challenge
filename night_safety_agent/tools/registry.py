"""도구 등록부 — LLM에 보여 줄 도구 설명(JSON 스키마)과 실행 함수 연결.

도구 결과는 세션 상태(state)에 저장해 화면 탭과 다음 도구가 재사용.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from . import data_layer as dl
from . import docs, safety


def today() -> date:
    hist, _ = dl.load("night_people")
    return pd.to_datetime(hist["date"]).max().date() + timedelta(days=1)


def resolve_period(period: str | None) -> tuple[str, int]:
    """'앞으로 7일'·'이번 주말'·'다음 주'·'YYYY-MM-DD' → (시작일, 일수)."""
    t = today()
    p = (period or "").strip()
    if p in ("", "앞으로 7일", "이번 주", "7일"):
        return t.isoformat(), 7
    if "주말" in p:
        sat = t + timedelta(days=(5 - t.weekday()) % 7)
        if "다음" in p:
            sat += timedelta(days=7)
        return sat.isoformat(), 2
    if "다음 주" in p or "다음주" in p:
        mon = t + timedelta(days=(7 - t.weekday()) % 7 or 7)
        return mon.isoformat(), 7
    if "내일" in p:
        return (t + timedelta(days=1)).isoformat(), 1
    try:
        return pd.to_datetime(p).date().isoformat(), 1
    except Exception:
        return t.isoformat(), 7


TOOLS = [
    {"name": "get_night_people", "description": "최근 4주 읍면동별 밤(21~03시) 인원 집계. 지역 현황 질문에 사용.",
     "params": {"region": "지역: '전체', '제주시', '서귀포시' 또는 읍면동명(쉼표 구분)"}},
    {"name": "forecast_safety", "description": "읍면동×날짜 야간 안전 수요 지수 예보와 1~3단계 등급. 순찰 계획·위험 시점 질문의 핵심 도구.",
     "params": {"region": "지역", "period": "기간: '앞으로 7일', '이번 주말', '다음 주', 'YYYY-MM-DD'"}},
    {"name": "backtest", "description": "지난 4주를 가리고 예보해 오차 계산, 기준선보다 나쁘면 기준선 채택. 예보 신뢰도 질문 또는 예보 직후 자동 실행.",
     "params": {"region": "지역"}},
    {"name": "plan_patrol", "description": "가장 최근 예보 결과로 순찰 권고표(추가 순찰 횟수·시간대·협조 대상) 작성. forecast_safety 이후 사용.",
     "params": {}},
    {"name": "find_blind_spots", "description": "밤 인원 많고 조명·CCTV 부족한 조명·CCTV 보강 후보 순위.",
     "params": {"region": "지역", "top": "후보 수 (기본 5)"}},
    {"name": "cctv_retention_priority", "description": "CCTV 보관 기간 연장 우선구역과 비용 계산.",
     "params": {"share": "선별 비율 0~1 (기본 0.3)"}},
    {"name": "simulate", "description": "만약에 시나리오: 행사(읍면동·날짜·증가율), 크루즈(읍면동·날짜·척수), 비(날짜·확률), 조명 추가(읍면동·개수) 조건으로 예보 재계산 후 기존과 비교.",
     "params": {"region": "지역", "period": "기간", "event_emd": "행사 읍면동", "event_date": "행사 날짜 YYYY-MM-DD", "event_uplift": "행사 인원 증가율 (예: 0.4)",
                "cruise_emd": "크루즈 입항 주변 읍면동", "cruise_date": "날짜", "cruise_ships": "척수",
                "rain_date": "비 오는 날짜", "rain_prob": "강수확률", "light_emd": "조명 추가 읍면동", "light_add": "추가 조명 수"}},
    {"name": "fact_check", "description": "제주 치안 관련 주장(예: 범죄율 1위)을 공식 통계로 판정. 판정·근거·출처 반환.",
     "params": {"question": "판정할 주장 원문"}},
    {"name": "night_guide", "description": "가장 최근 예보의 1단계 이상 지역에 대한 한·중·영 밤길 안내문 작성.", "params": {}},
    {"name": "weekly_report", "description": "가장 최근 예보·순찰 권고·보강 후보로 주간 보고서(HTML) 작성.", "params": {}},
    {"name": "check_export", "description": "가장 최근 예보 결과를 센터 반출 기준(10 미만·개인 속성)으로 검사하고 반출 신청서 초안 작성.", "params": {}},
]
TOOL_NAMES = [t["name"] for t in TOOLS]


def schema_for(fmt: str) -> list[dict]:
    """'anthropic' 또는 'openai' 형식 도구 스키마."""
    out = []
    for t in TOOLS:
        props = {k: {"type": "string", "description": v} for k, v in t["params"].items()}
        js = {"type": "object", "properties": props}
        if fmt == "anthropic":
            out.append({"name": t["name"], "description": t["description"], "input_schema": js})
        else:
            out.append({"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": js}})
    return out


def _f(x, default=None, cast=float):
    try:
        return cast(x) if x not in (None, "") else default
    except Exception:
        return default


def run_tool(name: str, args: dict, state: dict) -> safety.ToolResult:
    """도구 실행. state에 결과 저장 (화면 탭·후속 도구 재사용)."""
    a = args or {}
    region = a.get("region") or state.get("region") or "전체"
    if name == "get_night_people":
        r = safety.get_night_people(region)
    elif name == "forecast_safety":
        start, days = resolve_period(a.get("period") or state.get("period"))
        r = safety.forecast_safety(region, start, days)
        state["forecast"] = r
        state["region"], state["period"] = region, a.get("period") or state.get("period")
    elif name == "backtest":
        r = safety.backtest(region)
        state["backtest"] = r
    elif name == "plan_patrol":
        if "forecast" not in state:
            run_tool("forecast_safety", {"region": region}, state)
        use_sim = a.get("use") == "sim" and "sim_forecast" in state
        r = safety.plan_patrol((state["sim_forecast"] if use_sim else state["forecast"]).data)
        if use_sim:
            r.summary = "[가정 조건 반영] " + r.summary
        state["patrol"] = r
    elif name == "find_blind_spots":
        r = safety.find_blind_spots(region, _f(a.get("top"), 5, int))
        state["blind"] = r
    elif name == "cctv_retention_priority":
        r = safety.cctv_retention_priority(_f(a.get("share"), 0.3))
        state["cctv"] = r
    elif name == "simulate":
        start, days = resolve_period(a.get("period") or state.get("period"))
        scen = {"events": [], "cruise": [], "rain": {}, "add_lights": {}}
        if a.get("event_emd"):
            emd = (dl.resolve_region(a["event_emd"]) or [a["event_emd"]])[0]
            scen["events"].append({"date": a.get("event_date") or start, "emd": emd, "name": "가정 행사", "uplift": _f(a.get("event_uplift"), 0.4)})
        if a.get("cruise_emd"):
            emd = (dl.resolve_region(a["cruise_emd"]) or [a["cruise_emd"]])[0]
            scen["cruise"].append({"date": a.get("cruise_date") or start, "port": "가정", "emd": emd, "ships": _f(a.get("cruise_ships"), 1, int)})
        if a.get("rain_date"):
            scen["rain"][a["rain_date"]] = _f(a.get("rain_prob"), 80)
        if a.get("light_emd"):
            emd = (dl.resolve_region(a["light_emd"]) or [a["light_emd"]])[0]
            scen["add_lights"][emd] = _f(a.get("light_add"), 100)
        # 가정 날짜가 기간 밖이면 기간을 그 날짜까지 늘림
        dates = [d for d in (a.get("event_date"), a.get("cruise_date"), a.get("rain_date")) if d]
        for d in dates:
            gap = (pd.to_datetime(d).date() - pd.to_datetime(start).date()).days
            if gap >= days:
                days = gap + 1
            elif gap < 0:
                start, days = d, days - gap
        before = safety.forecast_safety(region, start, days)
        after = safety.forecast_safety(region, start, days, scen)
        key = ["날짜", "읍면동"]
        cmp_ = before.data[key + ["지수", "등급"]].merge(after.data[key + ["지수", "등급"]], on=key, suffixes=("_기존", "_변경"))
        cmp_["변화"] = (cmp_["지수_변경"] - cmp_["지수_기존"]).round(1)
        cmp_ = cmp_[cmp_.변화.abs() > 0.05].sort_values("변화", key=abs, ascending=False)
        up = (cmp_.등급_변경 > cmp_.등급_기존).sum()
        down = (cmp_.등급_변경 < cmp_.등급_기존).sum()
        r = safety.ToolResult(True, f"조건 변경 반영 — 영향 {len(cmp_)}건, 등급 상승 {up}건 · 하락 {down}건", cmp_.reset_index(drop=True),
                              after.sources, ["가정 조건 결과 — 확정 예보 아님"], {"scenario": scen})
        state["simulate"] = r
        state["sim_forecast"] = after
    elif name == "fact_check":
        r = safety.fact_check(a.get("question") or state.get("last_question", ""))
        state["fact"] = r
    elif name == "night_guide":
        if "forecast" not in state:
            run_tool("forecast_safety", {"region": region}, state)
        r = docs.night_guide(state["forecast"].data)
        state["guide"] = r
    elif name == "weekly_report":
        if "patrol" not in state:
            run_tool("plan_patrol", {}, state)
        r = docs.weekly_report(state["forecast"], state["patrol"], state.get("blind"), state.get("export"))
        state["report"] = r
    elif name == "check_export":
        if "forecast" not in state:
            run_tool("forecast_safety", {"region": region}, state)
        cols = ["날짜", "읍면동", "지수", "등급", "예보_밤인원"]
        r = safety.check_export(state["forecast"].data[cols])
        state["export"] = r
    else:
        r = safety.ToolResult(False, f"알 수 없는 도구 '{name}'")
    return r
