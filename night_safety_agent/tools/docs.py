"""완성물 작성 — 순찰 권고 보고서(HTML, 인쇄 → PDF), 한·중·영 밤길 안내문.

템플릿이 기본. LLM이 켜져 있으면 문장만 다듬고 숫자는 템플릿 값 그대로 사용.
"""
from __future__ import annotations

import html
from datetime import datetime

import pandas as pd

from .safety import ToolResult

GRADE_NAME = {3: "3단계", 2: "2단계", 1: "1단계", 0: "평상"}


def weekly_report(forecast: ToolResult, patrol: ToolResult, blind: ToolResult | None = None,
                  check: ToolResult | None = None) -> ToolResult:
    def tbl(df: pd.DataFrame, n=20):
        if df is None or df.empty:
            return "<p>해당 없음</p>"
        return df.head(n).to_html(index=False, border=0, classes="t")

    srcs = sorted(set(forecast.sources + patrol.sources + (blind.sources if blind else [])))
    notes = sorted(set(forecast.notes + patrol.notes + (blind.notes if blind else [])))
    body = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>주간 야간 순찰 권고 보고서</title>
<style>body{{font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif;margin:24px;color:#1d2433}}
h1{{color:#2649A4;border-bottom:3px solid #88C038;padding-bottom:6px}}h2{{color:#14296A;border-left:4px solid #2649A4;padding-left:8px}}
.t{{border-collapse:collapse;width:100%;font-size:12px}}.t th{{background:#2649A4;color:#fff;padding:4px}}.t td{{border-bottom:1px solid #d8e1ee;padding:3px 5px}}
.box{{background:#F7FBFF;border:1px solid #d8e1ee;padding:10px;border-radius:6px}}small{{color:#5a6680}}</style></head><body>
<h1>주간 야간 순찰 권고 보고서</h1>
<p><small>작성 {datetime.now():%Y-%m-%d %H:%M} · 밤길 안심 예보관 · 예보 기간 {html.escape(forecast.extra.get('period', ''))}</small></p>
<div class="box"><b>요약</b><br>{html.escape(forecast.summary)}<br>{html.escape(patrol.summary)}</div>
<h2>1. 순찰 권고</h2>{tbl(patrol.data)}
<h2>2. 안전 수요 예보 상위</h2>{tbl(forecast.data[['날짜','요일','읍면동','지수','등급','예보_밤인원','하한','상한','요인']] if forecast.data is not None else None, 15)}
<h2>3. 조명·CCTV 보강 후보</h2>{tbl(blind.data if blind else None)}
<h2>4. 근거·한계</h2><ul>{''.join(f'<li>{html.escape(s)}</li>' for s in srcs)}</ul>
<ul>{''.join(f'<li>{html.escape(s)}</li>' for s in notes)}</ul>
<p><small>지수 = 100 × 인원비 × √(위험 가중 × 밝기·감시 부족) × 규모계수 · 등급 120/140/170 · 숫자는 코드 계산값 · 개인 속성 미사용</small></p>
{f'<h2>5. 반출 검사</h2><p>{html.escape(check.summary)}</p>' if check else ''}
</body></html>"""
    return ToolResult(True, "주간 보고서 작성 완료 (브라우저 인쇄 → PDF 저장)", None, srcs, [], {"html": body})


GUIDE = {
    "ko": ("밤길 안심 안내", "{area} 지역은 {date} 밤 사람이 평소보다 많을 것으로 예상돼요.",
           ["가능하면 밝은 큰길로 이동해 주세요.", "자치경찰·경찰 순찰이 강화돼요 ({time}).", "위급할 땐 112, 관광 통역 안내는 1330."]),
    "zh": ("夜间安心出行指南", "预计{date}晚上{area}地区人流比平时多。",
           ["请尽量走明亮的大路。", "警察巡逻将加强（{time}）。", "紧急情况请拨打112，旅游翻译咨询请拨打1330。"]),
    "en": ("Safe Night Walk Guide", "{area} is expected to be busier than usual on the night of {date}.",
           ["Please use well-lit main streets when possible.", "Police patrols will be increased ({time}).", "Emergency: 112 · Tourist interpretation hotline: 1330."]),
}


def night_guide(forecast: pd.DataFrame, top: int = 3) -> ToolResult:
    f = forecast[forecast.등급 >= 1].sort_values("지수", ascending=False).head(top)
    if f.empty:
        return ToolResult(True, "1단계 이상 구역이 없어 별도 안내문 불필요", None)
    blocks = []
    for _, r in f.iterrows():
        time = "21~03시"
        for lang, (title, lead, items) in GUIDE.items():
            blocks.append({"언어": lang, "읍면동": r.읍면동, "날짜": r.날짜,
                           "안내문": f"[{title}]\n" + lead.format(area=r.읍면동, date=r.날짜) + "\n- " + "\n- ".join(i.format(time=time) for i in items)})
    t = pd.DataFrame(blocks)
    return ToolResult(True, f"밤길 안내문 {len(f)}개 지역 × 한·중·영 작성", t, [],
                      ["외부 공개용 — 등급·지수 대신 '밝은 길 안내' 형태로 표현 (동네 낙인 방지)"])
