"""데이터 층 — 센터 파일 → 공개 파일 → 예시 저장본 순서로 자동 선택.

같은 열 이름의 CSV를 data/center/ (센터 PC) 또는 data/public/ (공개 데이터 다운로드)에
넣으면 예시 저장본 대신 자동 사용. 어떤 출처를 썼는지 항상 함께 반환.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LAYERS = [
    ("center", DATA / "center", "제주빅데이터센터 (센터 PC)"),
    ("public", DATA / "public", "공개 데이터 (허브·공공데이터포털)"),
    ("sample", DATA / "sample", "예시 저장본 (실데이터 연결 전)"),
]

# 데이터 이름 → 파일명, 필수 열, 원 출처 설명
CATALOG = {
    "night_people": ("night_people.csv", ["date", "emd", "night_people"],
                     "밤(21~03시) 읍면동 생활인구 — 센터 4-11·4-13·4-15 집계 / 허브 읍면동 유동인구 API"),
    "infra": ("infra.csv", ["emd", "streetlights", "cctv"],
              "가로등(포털 15129786)·보안등·CCTV 표준데이터 읍면동 집계"),
    "risk_zone": ("risk_zone.csv", ["zone", "crimes_per_100k"],
                  "경찰서 권역 5대 범죄 (포털 15123527)"),
    "events": ("events.csv", ["date", "emd", "name", "uplift"], "행사·축제 (TourAPI)"),
    "cruise": ("cruise.csv", ["date", "port", "emd", "ships"], "크루즈 입항 일정 (제주도 발표)"),
    "visitors": ("visitors.csv", ["date", "visitors"], "지역별 방문자수 (관광공사 15101972)"),
    "weather_forecast": ("weather_forecast.csv", ["date", "rain_prob"], "기상청 단기·중기예보, 출몰시각"),
}


class DataMissing(Exception):
    pass


@lru_cache(maxsize=None)
def load(name: str) -> tuple[pd.DataFrame, str]:
    """(데이터, 사용한 출처 설명) 반환."""
    fname, cols, desc = CATALOG[name]
    for key, folder, label in LAYERS:
        p = folder / fname
        if p.exists():
            df = pd.read_csv(p)
            missing = [c for c in cols if c not in df.columns]
            if missing:
                continue  # 열이 맞지 않으면 다음 층으로
            return df, f"{label} · {desc}"
    raise DataMissing(f"{fname} 없음 — data/center, data/public, data/sample 어디에도 없음")


@lru_cache(maxsize=None)
def meta() -> pd.DataFrame:
    return pd.read_csv(DATA / "ref" / "emd_meta.csv")


@lru_cache(maxsize=None)
def geojson() -> dict:
    return json.load(open(DATA / "ref" / "jeju_emd.geojson", encoding="utf-8"))


@lru_cache(maxsize=None)
def holidays() -> set[str]:
    return set(pd.read_csv(DATA / "ref" / "holidays.csv")["date"].astype(str))


@lru_cache(maxsize=None)
def fact_cards() -> list[dict]:
    return json.load(open(DATA / "ref" / "fact_cards.json", encoding="utf-8"))


def using_sample(source: str) -> bool:
    return source.startswith("예시")


def clear_cache():
    for f in (load, meta, geojson, holidays, fact_cards):
        f.cache_clear()


def resolve_region(text: str | None) -> list[str]:
    """'제주시', '서귀포시', '전체', 읍면동명(쉼표 구분) → 읍면동 목록."""
    m = meta()
    if not text or text in ("전체", "제주도", "제주도 전체", "제주특별자치도"):
        return m.emd.tolist()
    t = text.replace(" 전체", "").strip()
    if t in ("제주시", "서귀포시"):
        return m[m.sgg == t].emd.tolist()
    names = [x.strip() for x in t.replace("·", ",").split(",") if x.strip()]
    hit = [n for n in names if n in set(m.emd)]
    if not hit:
        # 부분 일치 (예: '탑동' 같은 별칭은 별칭표로)
        alias = {"탑동": "삼도2동", "중문": "중문동", "서귀포 시내": "천지동", "제주공항": "용담2동", "애월": "애월읍", "성산": "성산읍", "함덕": "조천읍"}
        hit = [alias[n] for n in names if n in alias]
    return hit
