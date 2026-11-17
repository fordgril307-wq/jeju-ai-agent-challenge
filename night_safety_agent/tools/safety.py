"""2안-A 밤길 안심 예보관 — 계산 도구.

원칙: 모든 숫자는 이 파일의 pandas 계산으로만 생성. LLM은 도구 선택과 문장 작성만 담당.
안전 수요 지수 = 100 × 인원비 × √(위험 가중 × 밝기·감시 부족) × 규모계수
  - 인원비 = 예보 밤 인원 ÷ 지난 4주 같은 요일 기준선 (주간 변동의 중심)
  - 위험 가중·밝기·감시 부족 = 1.0 기준 고정 지도값 (제곱근으로 완화)
  - 규모계수 = (동네 기준선 ÷ 전체 중앙값) ^ 0.1 — 사람 많은 동네의 같은 증가에 조금 더 가중
등급: 120 이상 1단계 · 140 이상 2단계 · 170 이상 3단계
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import data_layer as dl

GRADE_CUTS = [(170, 3), (140, 2), (120, 1)]
VISITOR_ELASTICITY = {"관광": 0.8, "도심": 0.4, "주거": 0.2}
CRUISE_NIGHT_STAY = 450      # 크루즈 1척당 밤 시간대 주변 체류 추정 인원 (가정값, 설정으로 조정)
CCTV_RETENTION_COST = 80e8   # CCTV 보관 30→60일 전체 연장 시 연 추가 비용 (제이누리 2026.9)
NIGHT_BANDS = ("21~24시", "0~3시")


@dataclass
class ToolResult:
    ok: bool
    summary: str
    data: pd.DataFrame | None = None
    sources: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def brief(self, max_rows: int = 12) -> dict:
        """LLM에 넘길 요약 (표는 상위 행만)."""
        out = {"ok": self.ok, "summary": self.summary, "sources": self.sources, "notes": self.notes}
        if self.data is not None and len(self.data):
            out["rows"] = self.data.head(max_rows).to_dict(orient="records")
            out["total_rows"] = len(self.data)
        if self.extra:
            out["extra"] = {k: v for k, v in self.extra.items() if isinstance(v, (str, int, float, list, dict))}
        return out


# ------------------------------------------------------------------ 공통 계산
def _to_date(s) -> date:
    if isinstance(s, date):
        return s
    return pd.to_datetime(s).date()


def _history() -> tuple[pd.DataFrame, str]:
    df, src = dl.load("night_people")
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    if "rain" not in df.columns:
        df["rain"] = 0
    if "late_share" not in df.columns:
        df["late_share"] = 0.3
    return df, src


def _with_baseline(df: pd.DataFrame) -> pd.DataFrame:
    """각 행에 '이전 4주 같은 요일 평균' 기준선 추가."""
    df = df.sort_values(["emd", "date"]).copy()
    df["dow"] = df.date.dt.dayofweek
    df["baseline"] = (df.groupby(["emd", "dow"])["night_people"]
                        .transform(lambda s: s.shift(1).rolling(4, min_periods=3).mean()))
    return df


def _learn_coefs(hist: pd.DataFrame) -> dict:
    """과거 자료로 비·연휴 전날 효과를 유형별로 학습."""
    h = _with_baseline(hist).dropna(subset=["baseline"])
    h["ratio"] = h.night_people / h.baseline
    h = h.merge(dl.meta()[["emd", "type"]], on="emd")
    hol = dl.holidays()
    h["hol_eve"] = (h.date + pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d").isin(hol)
    coefs = {}
    for t, g in h.groupby("type"):
        base = g[(g.rain == 0) & (~g.hol_eve)].ratio.mean()
        coefs[t] = {
            "rain": float(g[g.rain == 1].ratio.mean() / base) if (g.rain == 1).any() else 0.92,
            "hol_eve": float(g[g.hol_eve].ratio.mean() / base) if g.hol_eve.any() else 1.08,
            "resid_sd": float(g.ratio.std()),
        }
    return coefs


def _visitor_factor(day: pd.Timestamp, vis: pd.DataFrame) -> float:
    v = vis.set_index("date")["visitors"]
    key = day.strftime("%Y-%m-%d")
    if key not in v.index:
        return 1.0
    past = [(day - pd.Timedelta(days=7 * k)).strftime("%Y-%m-%d") for k in range(1, 5)]
    past = [v[p] for p in past if p in v.index]
    return float(v[key] / np.mean(past)) if past else 1.0


def _risk_weight() -> tuple[pd.Series, str]:
    rz, src = dl.load("risk_zone")
    w = rz.set_index("zone")["crimes_per_100k"]
    w = (w / w.mean()).clip(0.85, 1.2)
    m = dl.meta().set_index("emd")
    return m["zone"].map(w).fillna(1.0), src


def _infra_weight() -> tuple[pd.DataFrame, str]:
    inf, src = dl.load("infra")
    inf = inf.set_index("emd").copy()
    road = inf["road_km"] if "road_km" in inf else dl.meta().set_index("emd")["area_km2"]
    lights = inf["streetlights"] + inf.get("security_lights", 0)
    inf["light_per_km"] = (lights / road).round(1)
    inf["cctv_per_km"] = (inf["cctv"] / road).round(2)
    ld = (inf.light_per_km.median() / inf.light_per_km.clip(lower=0.1)) ** 0.25
    cd = (inf.cctv_per_km.median() / inf.cctv_per_km.clip(lower=0.01)) ** 0.25
    inf["light_deficit"] = ld.clip(0.85, 1.25).round(3)
    inf["cctv_deficit"] = cd.clip(0.85, 1.25).round(3)
    inf["infra_w"] = ((inf.light_deficit + inf.cctv_deficit) / 2).round(3)
    return inf, src


def grade_of(idx: float) -> int:
    for cut, g in GRADE_CUTS:
        if idx >= cut:
            return g
    return 0


# ------------------------------------------------------------------ 도구 ①
def get_night_people(region: str = "전체", weeks: int = 4) -> ToolResult:
    emds = dl.resolve_region(region)
    if not emds:
        return ToolResult(False, f"'{region}' 지역을 찾지 못함")
    hist, src = _history()
    end = hist.date.max()
    h = hist[(hist.emd.isin(emds)) & (hist.date > end - pd.Timedelta(days=7 * weeks))]
    t = (h.groupby("emd").agg(평균_밤인원=("night_people", "mean"), 최대=("night_people", "max"), 늦은밤비중=("late_share", "mean"))
           .round(0).sort_values("평균_밤인원", ascending=False).reset_index().rename(columns={"emd": "읍면동"}))
    t["늦은밤비중"] = (h.groupby("emd").late_share.mean().reindex(t.읍면동).values * 100).round(0)
    notes = ["예시 저장본 사용 — 실데이터 연결 전 수치"] if dl.using_sample(src) else []
    return ToolResult(True, f"{len(emds)}개 읍면동, 최근 {weeks}주 밤(21~03시) 인원 집계 (~{end.date()})", t, [src], notes)


# ------------------------------------------------------------------ 도구 ②⑥ 예보
def forecast_safety(region: str = "전체", start: str | None = None, days: int = 7,
                    scenario: dict | None = None) -> ToolResult:
    """읍면동 × 날짜 안전 수요 지수 예보 (+ 오차 구간)."""
    emds = dl.resolve_region(region)
    if not emds:
        return ToolResult(False, f"'{region}' 지역을 찾지 못함")
    scenario = scenario or {}
    hist, src_people = _history()
    last = hist.date.max()
    start_d = pd.Timestamp(_to_date(start)) if start else last + pd.Timedelta(days=1)
    dates = [start_d + pd.Timedelta(days=i) for i in range(days)]

    coefs = _learn_coefs(hist)
    meta = dl.meta().set_index("emd")
    vis, src_vis = dl.load("visitors")
    wx, src_wx = dl.load("weather_forecast")
    wx = wx.set_index("date")
    ev, src_ev = dl.load("events")
    cr, src_cr = dl.load("cruise")
    risk_w, src_risk = _risk_weight()
    infra, src_inf = _infra_weight()
    hol = dl.holidays()

    # 시나리오: 행사·크루즈·비·조명 보강
    ev = ev.copy()
    for e in scenario.get("events", []):  # 같은 날·같은 동네 행사는 가정 조건으로 교체
        ev = ev[~((ev.date == e["date"]) & (ev.emd == e["emd"]))]
        ev = pd.concat([ev, pd.DataFrame([e])], ignore_index=True)
    cr = cr.copy()
    for c in scenario.get("cruise", []):
        cr = pd.concat([cr, pd.DataFrame([c])], ignore_index=True)
    for emd, add in scenario.get("add_lights", {}).items():
        if emd in infra.index:
            road = infra.loc[emd, "road_km"]
            new_density = infra.loc[emd, "light_per_km"] + add / road
            ld = (infra.light_per_km.median() / new_density) ** 0.25
            infra.loc[emd, "light_deficit"] = float(np.clip(ld, 0.85, 1.25))
            infra.loc[emd, "infra_w"] = round((infra.loc[emd, "light_deficit"] + infra.loc[emd, "cctv_deficit"]) / 2, 3)

    rows = []
    recent = hist[hist.date > hist.date.max() - pd.Timedelta(days=28)]
    med_base = float(recent.groupby("emd").night_people.mean().median())
    hh = hist[hist.emd.isin(emds)]
    for emd in emds:
        g = hh[hh.emd == emd]
        typ = meta.loc[emd, "type"]
        c = coefs.get(typ, {"rain": 0.92, "hol_eve": 1.08, "resid_sd": 0.06})
        late = float(g.late_share.iloc[-1]) if len(g) else 0.3
        for d in dates:
            same = g[(g.date.dt.dayofweek == d.dayofweek) & (g.date < start_d)].tail(4)
            if len(same) < 2:
                continue
            base = same.night_people.mean()
            f = 1.0
            why = []
            key = d.strftime("%Y-%m-%d")
            if (d + pd.Timedelta(days=1)).strftime("%Y-%m-%d") in hol:
                f *= c["hol_eve"]; why.append("연휴 전날")
            rp = scenario.get("rain", {}).get(key)
            if rp is None:
                rp = float(wx.loc[key, "rain_prob"]) if key in wx.index else 0.0
            if rp >= 60:
                f *= 1 + (c["rain"] - 1) * rp / 100; why.append(f"비 {int(rp)}%")
            vf = _visitor_factor(d, vis)
            f *= 1 + (vf - 1) * VISITOR_ELASTICITY.get(typ, 0.3)
            if abs(vf - 1) > 0.03:
                why.append(f"방문객 {vf - 1:+.0%}")
            e = ev[(ev.date == key) & (ev.emd == emd)]
            if len(e):
                f *= 1 + float(e.uplift.sum()); why.append(e.name.iloc[0])
            ships = cr[(cr.date == key) & (cr.emd == emd)].ships.sum()
            add = ships * CRUISE_NIGHT_STAY
            if ships:
                why.append(f"크루즈 {int(ships)}척")
            pred = base * f + add
            sd = c["resid_sd"] * base
            ratio = pred / base
            scale = (base / med_base) ** 0.1
            idx = 100 * ratio * (risk_w.get(emd, 1.0) * infra.loc[emd, "infra_w"]) ** 0.5 * scale
            rows.append({
                "날짜": key, "요일": "월화수목금토일"[d.dayofweek], "읍면동": emd, "시": meta.loc[emd, "sgg"],
                "권역": meta.loc[emd, "zone"], "예보_밤인원": round(pred), "하한": round(pred - 1.64 * sd), "상한": round(pred + 1.64 * sd),
                "기준선": round(base), "인원비": round(ratio, 3), "위험가중": round(float(risk_w.get(emd, 1.0)), 3),
                "밝기감시부족": float(infra.loc[emd, "infra_w"]), "지수": round(idx, 1), "등급": grade_of(idx),
                "21~24시": round(pred * (1 - late)), "0~3시": round(pred * late), "요인": ", ".join(why) or "평소",
            })
    out = pd.DataFrame(rows)
    if out.empty:
        return ToolResult(False, "예보에 필요한 과거 자료 부족")
    out = out.sort_values(["지수"], ascending=False).reset_index(drop=True)
    n3, n2, n1 = (out.등급 == 3).sum(), (out.등급 == 2).sum(), (out.등급 == 1).sum()
    period = f"{dates[0].date()} ~ {dates[-1].date()}"
    srcs = sorted({src_people, src_vis, src_wx, src_ev, src_cr, src_risk, src_inf})
    notes = ["숫자는 코드 계산값, 오차 구간은 과거 잔차 기준 90% 범위"]
    if any(dl.using_sample(s) for s in srcs):
        notes.insert(0, "일부 예시 저장본 사용 — 실데이터 연결 전 수치")
    return ToolResult(True, f"{period} · {len(emds)}개 읍면동 예보 — 3단계 {n3}건 · 2단계 {n2}건 · 1단계 {n1}건 (읍면동×일)",
                      out, srcs, notes, {"period": period, "coefs": coefs})


# ------------------------------------------------------------------ 도구 자기 검증
def backtest(region: str = "전체", weeks: int = 4) -> ToolResult:
    """지난 n주를 가리고 예보 → 오차(MAPE). 요일 기준선보다 나쁘면 기준선 채택."""
    emds = dl.resolve_region(region)
    hist, src = _history()
    hist = hist[hist.emd.isin(emds)]
    coefs = _learn_coefs(hist)
    h = _with_baseline(hist).dropna(subset=["baseline"]).merge(dl.meta()[["emd", "type"]], on="emd")
    cut = h.date.max() - pd.Timedelta(days=7 * weeks)
    test = h[h.date > cut].copy()
    hol = dl.holidays()
    eve = (test.date + pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d").isin(hol)
    rain_c = test.type.map(lambda t: coefs.get(t, {}).get("rain", 0.92))
    eve_c = test.type.map(lambda t: coefs.get(t, {}).get("hol_eve", 1.08))
    test["model"] = test.baseline * np.where(test.rain == 1, rain_c, 1.0) * np.where(eve, eve_c, 1.0)
    mape_m = float((abs(test.model - test.night_people) / test.night_people).mean() * 100)
    mape_b = float((abs(test.baseline - test.night_people) / test.night_people).mean() * 100)
    adopt = "모델" if mape_m <= mape_b else "요일 기준선"
    by = (test.assign(err=abs(test.model - test.night_people) / test.night_people * 100)
              .groupby("emd").err.mean().round(1).sort_values(ascending=False).reset_index()
              .rename(columns={"emd": "읍면동", "err": "오차율(%)"}))
    s = f"지난 {weeks}주 검증 — 모델 오차 {mape_m:.1f}% · 요일 기준선 {mape_b:.1f}% → {adopt} 채택"
    notes = ["검증 기간 비 여부는 실측값 사용 (실제 운영 시 예보값 사용)"]
    if dl.using_sample(src):
        notes.insert(0, "예시 저장본 기준 검증 — 실데이터 연결 후 재실행 필요")
    return ToolResult(True, s, by, [src], notes, {"mape_model": round(mape_m, 1), "mape_baseline": round(mape_b, 1), "adopted": adopt})


# ------------------------------------------------------------------ 도구 순찰 권고
def plan_patrol(forecast: pd.DataFrame) -> ToolResult:
    f = forecast[forecast.등급 >= 1].copy()
    if f.empty:
        return ToolResult(True, "1단계 이상 구역 없음 — 평소 순찰 유지", f)

    def rec(r):
        busy = "0~3시" if r["0~3시"] >= r["21~24시"] * 0.8 else "21~24시"
        if r.등급 == 3:
            return "추가 순찰 2회 (21~24시·0~3시 각 1회)", "자율방범대 합동 순찰 요청", 2
        if r.등급 == 2:
            return f"추가 순찰 1회 ({busy})", "지구대 거점 정차", 1
        return f"기존 경로에 거점 정차 1회 ({busy})", "—", 0

    f[["권고", "협조", "추가순찰"]] = f.apply(lambda r: pd.Series(rec(r)), axis=1)
    t = f[["날짜", "요일", "권역", "읍면동", "등급", "지수", "예보_밤인원", "권고", "협조", "요인"]].sort_values(["날짜", "등급"], ascending=[True, False])
    total = int(f.추가순찰.sum())
    stops = int((f.등급 == 1).sum())
    by_zone = f[f.추가순찰 > 0].groupby("권역").추가순찰.sum().to_dict()
    cnt = f.등급.value_counts()
    s = (f"3단계 {cnt.get(3, 0)}건 · 2단계 {cnt.get(2, 0)}건 · 1단계 {cnt.get(1, 0)}건 (읍면동×일) → "
         f"추가 순찰 {total}회, 거점 정차 {stops}회" + (" · " + " · ".join(f"{k} {int(v)}회" for k, v in by_zone.items()) if by_zone else ""))
    return ToolResult(True, s, t.reset_index(drop=True), [], ["권역은 경찰서 관할 근사 매핑 — 실제 관할표로 교체 필요"], {"total_extra": total})


# ------------------------------------------------------------------ 도구 사각지대
def find_blind_spots(region: str = "전체", top: int = 5) -> ToolResult:
    emds = dl.resolve_region(region)
    people = get_night_people(region).data.set_index("읍면동")["평균_밤인원"]
    infra, src_inf = _infra_weight()
    risk_w, src_risk = _risk_weight()
    df = infra.loc[[e for e in emds if e in infra.index]].copy()
    df["평균_밤인원"] = people.reindex(df.index)
    df["위험가중"] = risk_w.reindex(df.index)
    p = df.평균_밤인원 / df.평균_밤인원.median()
    df["사각지대점수"] = (100 * p ** 0.5 * df.light_deficit * df.cctv_deficit * df.위험가중).round(1)
    t = (df.sort_values("사각지대점수", ascending=False).head(top).reset_index().rename(columns={
        "emd": "읍면동", "light_per_km": "조명/도로km", "cctv_per_km": "CCTV/도로km"}))
    t["근거"] = t.apply(lambda r: f"밤 인원 {int(r.평균_밤인원):,}명 · 조명 {r['조명/도로km']}개/km (중앙값 {infra.light_per_km.median():.1f}) · CCTV {r['CCTV/도로km']}대/km", axis=1)
    t = t[["읍면동", "사각지대점수", "평균_밤인원", "조명/도로km", "CCTV/도로km", "근거"]]
    srcs = sorted({src_inf, src_risk})
    notes = ["사람 많고 어두운 곳 우선 — 국적·성별 등 개인 속성 미사용"]
    if any(dl.using_sample(s) for s in srcs):
        notes.insert(0, "예시 저장본 사용 — 가로등·CCTV 실데이터 연결 전 수치")
    return ToolResult(True, f"조명·CCTV 보강 후보 상위 {top}곳: " + ", ".join(t.읍면동), t, srcs, notes)


def cctv_retention_priority(share: float = 0.3) -> ToolResult:
    """CCTV 보관 연장 우선구역 — 밤 인원 × CCTV 대수 순으로 전체 대수의 share만큼."""
    infra, src = _infra_weight()
    people = get_night_people("전체").data.set_index("읍면동")["평균_밤인원"]
    df = infra[["cctv"]].copy()
    df["평균_밤인원"] = people.reindex(df.index)
    df["우선도"] = df.평균_밤인원 / df.cctv.clip(lower=1)
    df = df.sort_values("우선도", ascending=False)
    df["누적비중"] = df.cctv.cumsum() / df.cctv.sum()
    sel = df[df.누적비중.shift(fill_value=0) < share]
    cost = CCTV_RETENTION_COST * sel.cctv.sum() / df.cctv.sum()
    t = sel.reset_index().rename(columns={"emd": "읍면동", "cctv": "CCTV대수"})[["읍면동", "CCTV대수", "평균_밤인원"]]
    s = (f"우선구역 {len(t)}곳 (CCTV {int(sel.cctv.sum()):,}대, 전체의 {sel.cctv.sum() / df.cctv.sum():.0%}) — "
         f"연 추가 비용 약 {cost / 1e8:.0f}억 원 (전체 연장 80억 원 대비 약 {(CCTV_RETENTION_COST - cost) / 1e8:.0f}억 원 절감)")
    return ToolResult(True, s, t, [src, "CCTV 보관 연장 비용: 제이누리 2026.9 (연 약 80억 원)"],
                      ["선별 비율은 가정값 — 담당 부서가 조정", "카메라 1대당 같은 비용 가정"])


# ------------------------------------------------------------------ 도구 팩트체크
def fact_check(question: str) -> ToolResult:
    cards = dl.fact_cards()
    scored = sorted(((sum(k in question for k in c["keywords"]), c) for c in cards), key=lambda x: -x[0])
    if not scored or scored[0][0] == 0:
        return ToolResult(True, "확인 안 됨 — 공식 근거 카드에 없는 주장", None, [],
                          ["근거 없는 판정은 하지 않음. 담당 부서 확인 필요 주제로 기록"], {"verdict": "확인 안 됨"})
    c = scored[0][1]
    t = pd.DataFrame(c["figures"]).rename(columns={"label": "항목", "value": "값", "unit": "단위", "official": "공식"})
    t["공식"] = t["공식"].map({True: "공식", False: "비공식 (계산 방식 다름)"})
    return ToolResult(True, f"[{c['verdict']}] {c['summary']}", t, c["sources"], [f"기준: {c['basis_date']}"],
                      {"verdict": c["verdict"], "claim": c["claim"], "efforts": c["efforts"]})


# ------------------------------------------------------------------ 도구 반출 검사
PERSONAL_COLS = ("국적", "성별", "연령", "이름", "성명", "전화", "주민", "태그", "카드번호")


def check_export(table: pd.DataFrame, count_cols: list[str] | None = None) -> ToolResult:
    issues, t = [], table.copy()
    for c in t.columns:
        if any(k in str(c) for k in PERSONAL_COLS):
            issues.append(f"개인 속성 열 '{c}' 제거")
            t = t.drop(columns=c)
    count_cols = count_cols or [c for c in t.columns if any(k in str(c) for k in ("인원", "건수", "명"))]
    masked = 0
    for c in count_cols:
        if c in t and pd.api.types.is_numeric_dtype(t[c]):
            m = t[c] < 10
            masked += int(m.sum())
            t[c] = t[c].astype(object).where(~m, "10 미만")
    if masked:
        issues.append(f"10 미만 칸 {masked}개 '10 미만'으로 표시")
    ok = True
    s = "반출 기준 검사 통과" + (f" (자동 수정 {len(issues)}건)" if issues else " (수정 사항 없음)")
    draft = ("[반출 신청서 초안]\n- 반출 목적: 야간 순찰·조명 우선순위 산출 결과 공유\n"
             f"- 반출 자료: 읍면동·날짜 단위 안전 수요 지수 및 등급 ({len(t)}행)\n"
             "- 개인정보: 없음 (읍면동 집계값만 포함, 개인 속성 열 없음)\n"
             "- 10 미만 처리: 자동 '10 미만' 표시\n- 원천: 센터 유동인구 집계(응용집계), 공개 데이터")
    return ToolResult(ok, s, t, ["제주빅데이터센터 반출 기준 (10 미만 처리, 개인 식별 정보 제외)"], issues, {"draft": draft})
