"""밤길 안심 예보관 — Streamlit 화면.

실행: streamlit run app.py  (Windows: run.bat)
왼쪽: 대화·작업 기록 · 오른쪽: 완성물 탭 · 아래: 승인
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

from agent import core  # noqa: E402
from agent.llm import config as llm_config  # noqa: E402
from tools import data_layer as dl  # noqa: E402
from tools.registry import today  # noqa: E402

st.set_page_config(page_title="밤길 안심 예보관", page_icon="🌙", layout="wide")
st.markdown("""<style>
.block-container{padding-top:1.2rem}
.step{font-size:13px;padding:2px 0;border-bottom:1px dashed #e3e8f2}
.ok{color:#2e7d32}.ng{color:#c62828}.wn{color:#b26a00}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;background:#e6eefb;color:#2649A4;font-size:12px;margin-right:4px}
</style>""", unsafe_allow_html=True)

EXAMPLES = ["이번 주말 제주시 밤 순찰 어디부터?", "다음 주 밤 순찰 어디부터?", "가로등 더 달 곳 TOP 5",
            "탑동 11/20 행사 50%면 인력 얼마나?", "제주 범죄율 1위 진짜야?", "CCTV 보관 60일 어디부터?",
            "이 결과 밖으로 가져가도 돼? 제주시"]

ss = st.session_state
ss.setdefault("state", {})
ss.setdefault("turns", [])
ss.setdefault("pending", None)

# ------------------------------------------------------------------ 사이드바
with st.sidebar:
    st.header("🌙 밤길 안심 예보관")
    st.caption("자치경찰 야간 순찰 계획 담당용 AI 에이전트")
    cfg = llm_config()
    mode = st.radio("두뇌 (LLM)", ["자동 (설정된 LLM 사용, 실패 시 규칙)", "규칙만 (오프라인)"], index=0)
    st.caption(f"설정: `{cfg['provider']}` {cfg['model']}" if cfg["provider"] != "none" else "설정: LLM 없음 → 규칙 라우터")
    st.divider()
    st.subheader("데이터 출처")
    for name in dl.CATALOG:
        try:
            _, src = dl.load(name)
            icon = "🟡" if dl.using_sample(src) else "🟢"
            st.caption(f"{icon} **{name}** — {src.split(' · ')[0]}")
        except dl.DataMissing:
            st.caption(f"🔴 **{name}** — 없음")
    st.caption("🟢 실데이터 · 🟡 예시 저장본 (data/center 또는 data/public 에 같은 열 이름 CSV를 넣으면 자동 교체)")
    st.caption(f"기준일: {today()}")
    if st.button("대화 초기화"):
        ss.state, ss.turns, ss.pending = {}, [], None
        st.rerun()


def ask(q: str, region: str | None = None):
    use_llm = mode.startswith("자동")
    turn = core.run(q, ss.state, use_llm=use_llm, region_override=region)
    ss.turns.append(turn)
    ss.pending = q if turn.clarify else None


left, right = st.columns([5, 7], gap="large")

# ------------------------------------------------------------------ 왼쪽: 대화·작업 기록
with left:
    st.subheader("무엇을 도와드릴까요?")
    cols = st.columns(2)
    for i, ex in enumerate(EXAMPLES):
        if cols[i % 2].button(ex, key=f"ex{i}", use_container_width=True):
            ask(ex)
    with st.form("q", clear_on_submit=True):
        q = st.text_input("요청 입력", placeholder="예: 이번 주말 밤 순찰 어디부터?")
        if st.form_submit_button("보내기", type="primary") and q.strip():
            ask(q.strip())

    for ti, t in enumerate(reversed(ss.turns)):
        with st.container(border=True):
            st.markdown(f"**🙋 {t.question}**  <span class='badge'>{t.mode}</span>", unsafe_allow_html=True)
            with st.expander("작업 기록", expanded=(ti == 0)):
                for s in t.steps:
                    cls = {"✓": "ok", "✗": "ng", "!": "wn"}.get(s.status, "")
                    sec = f" · {s.secs}s" if s.secs else ""
                    st.markdown(f"<div class='step'><b class='{cls}'>{s.status}</b> <b>{s.name}</b> — {s.detail}{sec}</div>", unsafe_allow_html=True)
            st.markdown(t.answer.replace("\n", "  \n"))
            if t.clarify and ti == 0 and ss.pending:
                bc = st.columns(len(t.clarify))
                for j, opt in enumerate(t.clarify):
                    if bc[j].button(opt, key=f"cl{len(ss.turns)}{j}"):
                        ask(ss.pending, region=opt)
                        st.rerun()

# ------------------------------------------------------------------ 오른쪽: 완성물
S = ss.state


def _color(v):
    # 지수 → 색 (80 하늘 · 120 노랑 · 140 주황 · 170 빨강)
    stops = [(80, (247, 251, 255)), (110, (158, 202, 225)), (120, (254, 224, 139)), (140, (253, 174, 97)), (170, (215, 48, 31))]
    if v <= stops[0][0]:
        c = stops[0][1]
    elif v >= stops[-1][0]:
        c = stops[-1][1]
    else:
        for (a, ca), (b, cb) in zip(stops, stops[1:]):
            if a <= v <= b:
                k = (v - a) / (b - a)
                c = tuple(int(ca[i] + (cb[i] - ca[i]) * k) for i in range(3))
                break
    return f"rgb{c}"


def emd_map(agg: pd.DataFrame):
    """인터넷 없이 그리는 읍면동 지도 (plotly 좌표 평면 + 다각형 채우기)."""
    import plotly.graph_objects as go
    val = agg.set_index("읍면동")
    fig = go.Figure()
    for f in dl.geojson()["features"]:
        emd = f["properties"]["emd"]
        v = float(val.지수.get(emd, 90)) if emd in val.index else None
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for poly in polys:
            xs, ys = zip(*poly[0])
            txt = f"{emd}<br>지수 {v:.0f} · 등급 {int(val.등급.get(emd, 0))}<br>밤 인원 {int(val.예보_밤인원.get(emd, 0)):,}" if v is not None else emd
            fig.add_trace(go.Scatter(x=xs, y=ys, fill="toself", mode="lines", line=dict(color="#7a8aa6", width=0.6),
                                     fillcolor=_color(v) if v is not None else "#eeeeee", hoverinfo="text", text=txt, showlegend=False))
    top = agg.sort_values("지수", ascending=False).head(3)
    m = dl.meta().set_index("emd")
    fig.add_trace(go.Scatter(x=[m.loc[e, "lon"] for e in top.읍면동], y=[m.loc[e, "lat"] for e in top.읍면동], mode="text",
                             text=[f"<b>{e}</b>" for e in top.읍면동], textfont=dict(size=11, color="#14296A"), showlegend=False, hoverinfo="skip"))
    fig.update_xaxes(visible=False, range=[126.14, 126.98])   # 본섬 기준 (추자면은 지도 밖, 표에는 포함)
    fig.update_yaxes(visible=False, range=[33.18, 33.58], scaleanchor="x", scaleratio=1.2)
    fig.update_layout(height=340, margin=dict(l=0, r=0, t=0, b=0), plot_bgcolor="white")
    return fig


def show(r, height=None):
    if r is None:
        st.info("아직 결과가 없어요. 왼쪽에서 요청해 주세요.")
        return
    st.markdown(f"**{r.summary}**")
    if r.data is not None and len(r.data):
        st.dataframe(r.data, use_container_width=True, hide_index=True, **({"height": height} if height else {}))
    for n in r.notes:
        st.caption("※ " + n)
    if r.sources:
        st.caption("출처: " + " / ".join(r.sources))


with right:
    tabs = st.tabs(["🗺️ 예보판", "🚓 순찰 권고", "💡 사각지대", "🔎 팩트체크", "🔁 만약에", "🌐 밤길 안내", "📄 보고서", "📦 반출", "✅ 검증"])
    with tabs[0]:
        f = S.get("forecast")
        if f is None:
            st.info("순찰 계획을 요청하면 7일 예보판이 여기에 표시돼요.")
        else:
            d = f.data
            days = sorted(d.날짜.unique())
            pick = st.select_slider("날짜", options=["기간 최대"] + days, value="기간 최대")
            dd = d if pick == "기간 최대" else d[d.날짜 == pick]
            agg = dd.groupby("읍면동", as_index=False).agg(지수=("지수", "max"), 등급=("등급", "max"), 예보_밤인원=("예보_밤인원", "max"))
            fig = emd_map(agg)
            st.plotly_chart(fig, use_container_width=True)
            piv = d.pivot_table(index="읍면동", columns="날짜", values="지수").round(0)
            piv = piv.loc[piv.max(axis=1).sort_values(ascending=False).index].head(12)
            st.caption("읍면동 × 날짜 안전 수요 지수 (상위 12곳) · 120 이상 1단계 · 140 이상 2단계 · 170 이상 3단계")
            st.dataframe(piv.style.background_gradient(cmap="OrRd", vmin=90, vmax=180).format("{:.0f}"), use_container_width=True)
            show(f, height=220)
    with tabs[1]:
        show(S.get("patrol"))
        if S.get("patrol") is not None:
            with st.expander("현장 결과 기록 (선순환 데이터)"):
                with st.form("fb"):
                    c1, c2, c3 = st.columns(3)
                    emd = c1.selectbox("읍면동", dl.meta().emd.tolist())
                    done = c2.selectbox("순찰 실행", ["실행", "일부 실행", "미실행"])
                    issue = c3.selectbox("현장 특이사항", ["없음", "어두운 구간", "고장 가로등", "취약 시설"])
                    if st.form_submit_button("기록 저장"):
                        con = sqlite3.connect(ROOT / "data" / "feedback" / "feedback.sqlite")
                        con.execute("create table if not exists field(ts, emd, done, issue)")
                        con.execute("insert into field values (?,?,?,?)", (datetime.now().isoformat(timespec="seconds"), emd, done, issue))
                        con.commit(); con.close()
                        st.success("기록 저장 — 다음 주 보정에 반영")
    with tabs[2]:
        show(S.get("blind"))
        if S.get("cctv") is not None:
            st.divider(); show(S.get("cctv"))
    with tabs[3]:
        r = S.get("fact")
        if r is None:
            st.info("예: '제주 범죄율 1위 진짜야?'")
        else:
            v = r.extra.get("verdict", "")
            color = {"사실": "🟢", "일부 사실": "🟡", "사실 아님": "🔴"}.get(v, "⚪")
            st.markdown(f"### {color} {v}")
            if r.extra.get("claim"):
                st.caption("주장: " + r.extra["claim"])
            show(r)
            if r.extra.get("efforts"):
                st.markdown("**실제 노력**  \n" + "  \n".join("- " + e for e in r.extra["efforts"]))
    with tabs[4]:
        show(S.get("simulate"))
    with tabs[5]:
        g = S.get("guide")
        if g is None and S.get("forecast") is not None:
            if st.button("안내문 만들기"):
                from tools.registry import run_tool
                run_tool("night_guide", {}, S); st.rerun()
        if g is not None:
            st.markdown(f"**{g.summary}**")
            if g.data is not None:
                for _, row in g.data.iterrows():
                    st.text_area(f"{row.읍면동} · {row.날짜} · {row.언어}", row.안내문, height=110)
            for n in g.notes:
                st.caption("※ " + n)
    with tabs[6]:
        r = S.get("report")
        if r is None:
            st.info("순찰 계획을 요청하면 주간 보고서가 만들어져요.")
        else:
            st.markdown(f"**{r.summary}**")
            st.download_button("보고서 내려받기 (HTML → 브라우저 인쇄로 PDF)", r.extra["html"], file_name=f"야간순찰권고_{today()}.html", mime="text/html")
            st.components.v1.html(r.extra["html"], height=520, scrolling=True)
    with tabs[7]:
        r = S.get("export")
        show(r)
        if r is not None:
            st.code(r.extra.get("draft", ""), language=None)
    with tabs[8]:
        show(S.get("backtest"))

    # 승인
    if S.get("patrol") is not None:
        with st.container(border=True):
            st.markdown("**담당자 확인 사항**  \n- 권고 구역·시간대가 현장 일정과 맞는지  \n- 예시 저장본 표시가 있으면 실데이터 연결 후 다시 실행")
            c1, c2 = st.columns(2)
            if c1.button("✏️ 수정 요청", use_container_width=True):
                st.info("수정할 내용을 왼쪽에 입력해 주세요. 예: '삼도2동은 제외하고 다시'")
            if c2.button("✅ 승인", type="primary", use_container_width=True):
                con = sqlite3.connect(ROOT / "data" / "feedback" / "feedback.sqlite")
                con.execute("create table if not exists approved(ts, date, emd, grade, rec)")
                for _, row in S["patrol"].data.iterrows():
                    con.execute("insert into approved values (?,?,?,?,?)", (datetime.now().isoformat(timespec="seconds"), row.날짜, row.읍면동, int(row.등급), row.권고))
                con.commit(); con.close()
                st.success("승인 완료 — 순찰 권고 확정, 기록 저장")
