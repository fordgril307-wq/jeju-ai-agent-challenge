"""규칙 라우터 — LLM이 없거나 실패해도 끝까지 동작하는 기본 두뇌.

문장에서 의도·지역·기간을 뽑아 정해진 도구 순서(계획)를 만든다.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from tools import data_layer as dl
from tools.registry import today

INTENTS = [
    ("export", r"반출|밖으로|가져가"),
    ("fact", r"범죄율|1위|진짜|사실이|괴담|늘었|증가했|위험하다던"),
    ("cctv", r"보관|60일"),
    ("simulate", r"만약|행사|크루즈|비 오면|비가 오면|인력|늘면|추가하면|달면|설치하면"),
    ("blind", r"가로등|조명|CCTV|cctv|사각지대|어두운"),
    ("report", r"보고서"),
    ("guide", r"안내문|안내"),
    ("status", r"현황|몇 명|사람 많"),
    ("patrol", r"순찰|어디부터|계획|주말|다음 주|다음주|이번 주"),
]

PLANS = {
    "patrol": ["forecast_safety", "backtest", "plan_patrol", "weekly_report"],
    "blind": ["find_blind_spots"],
    "cctv": ["cctv_retention_priority"],
    "fact": ["fact_check"],
    "simulate": ["simulate", "plan_patrol"],
    "export": ["forecast_safety", "check_export"],
    "report": ["forecast_safety", "plan_patrol", "find_blind_spots", "weekly_report"],
    "guide": ["forecast_safety", "night_guide"],
    "status": ["get_night_people"],
}

ALIASES = {"탑동": "삼도2동", "중문": "중문동", "제주공항": "용담2동", "함덕": "조천읍", "애월": "애월읍", "성산": "성산읍", "강정": "대천동", "제주항": "건입동"}


def detect_intent(text: str) -> str:
    for name, pat in INTENTS:
        if re.search(pat, text):
            return name
    return "patrol"


def detect_region(text: str) -> str | None:
    if re.search(r"전체|제주도 전체|도 전체|제주 전역", text):
        return "전체"
    for sgg in ("서귀포시", "제주시"):
        if sgg in text:
            return sgg
    names = set(dl.meta().emd)
    hit = [n for n in names if n in text]
    hit += [v for k, v in ALIASES.items() if k in text]
    return ",".join(dict.fromkeys(hit)) if hit else None


def detect_date(text: str) -> str | None:
    t = today()
    m = re.search(r"(\d{1,2})\s*[/월.]\s*(\d{1,2})", text)
    if m:
        return date(t.year, int(m.group(1)), int(m.group(2))).isoformat()
    for i, wd in enumerate("월화수목금토일"):
        if re.search(wd + "요일", text):
            return (t + timedelta(days=(i - t.weekday()) % 7)).isoformat()
    if "내일" in text:
        return (t + timedelta(days=1)).isoformat()
    return None


def detect_period(text: str) -> str:
    if "다음 주말" in text:
        return "다음 주말"
    if "주말" in text:
        return "이번 주말"
    if "다음 주" in text or "다음주" in text:
        return "다음 주"
    return "앞으로 7일"


def parse(text: str) -> dict:
    intent = detect_intent(text)
    region = detect_region(text)
    d = detect_date(text)
    args = {"region": region, "period": detect_period(text)}
    if intent == "simulate":
        emd = region if region and region not in ("전체", "제주시", "서귀포시") else None
        if "크루즈" in text:
            n = re.search(r"(\d+)\s*척", text)
            args.update(cruise_emd=emd or "건입동", cruise_date=d, cruise_ships=n.group(1) if n else "2")
        elif "조명" in text or "가로등" in text:
            n = re.search(r"(\d+)\s*개", text)
            args.update(light_emd=emd or "삼도2동", light_add=n.group(1) if n else "100")
        elif "비" in text:
            args.update(rain_date=d, rain_prob="90")
        else:
            p = re.search(r"(\d+)\s*%", text)
            args.update(event_emd=emd or "삼도2동", event_date=d, event_uplift=str(int(p.group(1)) / 100) if p else "0.4")
        args["region"] = "제주시" if (emd and emd in set(dl.meta()[dl.meta().sgg == "제주시"].emd)) else ("서귀포시" if emd else "전체")
    if intent == "blind":
        n = re.search(r"(\d+)\s*(곳|개|위)|TOP\s*(\d+)|top\s*(\d+)", text)
        if n:
            args["top"] = next(g for g in n.groups() if g and g.isdigit())
    if intent == "fact":
        args["question"] = text
    if intent == "simulate":
        args["use"] = "sim"
    needs_region = intent in ("patrol", "report", "guide", "export") and region is None
    return {"intent": intent, "args": args, "plan": PLANS[intent], "clarify": needs_region}


CLARIFY_OPTIONS = ["제주도 전체", "제주시", "서귀포시"]
