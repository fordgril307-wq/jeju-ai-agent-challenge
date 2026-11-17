"""에이전트 루프 — 목표 이해 → 계획 → 도구 호출 → 검증 → 완성물 → 승인 요청.

LLM이 켜져 있으면 LLM이 도구를 고르고, 꺼져 있거나 실패하면 규칙 라우터 계획으로 이어서 실행.
모든 단계는 steps 기록(✓ 성공 · ✗ 실패 · ! 우회)으로 화면에 표시.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from tools import data_layer as dl
from tools.registry import TOOL_NAMES, resolve_period, run_tool

from . import router

SYSTEM = """너는 제주자치경찰단 야간 순찰 계획 담당자를 돕는 '밤길 안심 예보관' 에이전트.
규칙:
- 숫자는 반드시 도구 결과에서만 인용. 직접 계산하거나 추정한 숫자 금지.
- 순찰·위험 시점 질문: forecast_safety → backtest → plan_patrol 순서, 필요하면 weekly_report.
- 조명·CCTV 보강: find_blind_spots, CCTV 보관 연장: cctv_retention_priority.
- 범죄율 등 주장 확인: fact_check. 근거 카드에 없으면 '확인 안 됨'으로 답.
- 조건 변경(행사·크루즈·비·조명 추가): simulate.
- 결과를 밖으로 가져가는 질문: check_export.
- 국적·성별·연령 등 개인 속성으로 판단하지 않음. 개별 사건은 다루지 않음.
- 최종 답: 한국어, 5줄 이내 요약 + 담당자가 확인할 사항 1~2개. 예시 저장본 사용 시 그 사실을 밝힘.
"""


@dataclass
class Step:
    kind: str          # plan · tool · llm · clarify · final
    name: str
    status: str        # ✓ · ✗ · !
    detail: str
    secs: float = 0.0


@dataclass
class Turn:
    question: str
    steps: list[Step] = field(default_factory=list)
    answer: str = ""
    clarify: list[str] = field(default_factory=list)
    mode: str = "규칙"


def _exec(name: str, args: dict, state: dict, turn: Turn):
    t0 = time.time()
    try:
        r = run_tool(name, args, state)
        st = "✓" if r.ok else "✗"
        turn.steps.append(Step("tool", name, st, r.summary, round(time.time() - t0, 2)))
        if r.ok and any(dl.using_sample(s) for s in r.sources):
            turn.steps[-1].detail += "  ·  [예시 저장본]"
        return r
    except Exception as e:  # 도구 실패 → 기록 후 계속
        turn.steps.append(Step("tool", name, "✗", f"실패: {e}", round(time.time() - t0, 2)))
        return None


def _rule_answer(state: dict, plan: list[str]) -> str:
    keys = {"forecast_safety": "forecast", "backtest": "backtest", "plan_patrol": "patrol", "find_blind_spots": "blind",
            "cctv_retention_priority": "cctv", "simulate": "simulate", "fact_check": "fact", "night_guide": "guide",
            "weekly_report": "report", "check_export": "export", "get_night_people": None}
    lines = []
    for n in plan:
        k = keys.get(n)
        if k and k in state:
            lines.append(f"- {state[k].summary}")
    if "fact" in state and "fact_check" in plan:
        ef = state["fact"].extra.get("efforts")
        if ef:
            lines.append("- 실제 조치: " + " / ".join(ef))
    notes = {n for k in ("forecast", "blind", "fact") if k in state for n in state[k].notes if "예시" in n}
    if notes:
        lines.append("- ※ " + next(iter(notes)))
    lines.append("확인 사항: 권고 내용을 검토하고 [승인] 또는 [수정 요청]을 눌러 주세요.")
    return "\n".join(lines)


def run(question: str, state: dict, use_llm: bool = True, region_override: str | None = None) -> Turn:
    turn = Turn(question)
    state["last_question"] = question
    p = router.parse(question)
    if region_override:
        p["args"]["region"] = region_override
        p["clarify"] = False
    turn.steps.append(Step("plan", "목표 이해", "✓", f"의도: {p['intent']} · 지역: {p['args'].get('region') or '미정'} · 기간: {p['args'].get('period')}"))

    if p["clarify"]:
        turn.clarify = router.CLARIFY_OPTIONS
        turn.steps.append(Step("clarify", "되묻기", "!", "지역이 빠져 있어 확인 요청"))
        turn.answer = "어느 지역의 계획을 세울까요?"
        return turn

    from .llm import config as _cfg
    if use_llm and _cfg()["provider"] == "none":
        turn.steps.append(Step("llm", "두뇌", "✓", "LLM 미설정 → 규칙 라우터로 실행 (.env 에서 LLM 켜기 가능)"))
        use_llm = False
    if use_llm:
        try:
            from .llm import LLM
            llm = LLM(SYSTEM)
            turn.mode = llm.label
            hint = f"(참고: 지역={p['args'].get('region') or '전체'}, 기간={p['args'].get('period')}, 기준일={resolve_period(None)[0]})"
            llm.user(question + "\n" + hint)
            for _ in range(8):
                t0 = time.time()
                kind, payload = llm.step()
                if kind == "text":
                    turn.steps.append(Step("llm", "답변 작성", "✓", "도구 결과로 답변 작성", round(time.time() - t0, 2)))
                    turn.answer = payload.strip()
                    break
                turn.steps.append(Step("llm", "도구 선택", "✓", ", ".join(n for _, n, _ in payload), round(time.time() - t0, 2)))
                outs = []
                for cid, name, args in payload:
                    if name not in TOOL_NAMES:
                        outs.append((cid, json.dumps({"ok": False, "summary": "없는 도구"}, ensure_ascii=False)))
                        continue
                    r = _exec(name, args, state, turn)
                    brief = r.brief() if r else {"ok": False, "summary": "도구 실패 — 다른 방법 사용"}
                    outs.append((cid, json.dumps(brief, ensure_ascii=False, default=str)[:6000]))
                llm.tool_results(outs)
            if turn.answer:
                return turn
            turn.steps.append(Step("llm", "LLM", "!", "단계 한도 도달 → 규칙 계획으로 마무리"))
        except Exception as e:
            turn.steps.append(Step("llm", "LLM 연결", "!", f"사용 불가 ({type(e).__name__}) → 규칙 라우터로 우회"))
            turn.mode = "규칙 (LLM 우회)"

    turn.steps.append(Step("plan", "계획 수립", "✓", " → ".join(p["plan"])))
    for name in p["plan"]:
        args = dict(p["args"])
        _exec(name, args, state, turn)
    if "backtest" in state and "backtest" in p["plan"]:
        bt = state["backtest"].extra
        st = "✓" if bt.get("adopted") == "모델" else "!"
        turn.steps.append(Step("tool", "자기 검증 판정", st, f"{bt.get('adopted')} 채택 (모델 {bt.get('mape_model')}% vs 기준선 {bt.get('mape_baseline')}%)"))
    turn.answer = _rule_answer(state, p["plan"])
    turn.steps.append(Step("final", "승인 요청", "!", "담당자 확인 대기"))
    return turn
