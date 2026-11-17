"""예시 저장본 데이터 생성 스크립트.

실제 데이터 연결 전에도 에이전트 전체 흐름이 돌아가도록 만든 **예시 데이터**.
- 읍면동 경계: 실제 (통계청 행정동 경계, vuski/admdongkor ver20250401)
- 밤 인원·가로등·CCTV·권역 범죄 수치·행사: 예시 값 (구조만 실제 데이터와 동일)
실데이터는 data/center/ 또는 data/public/ 에 같은 열 이름으로 넣으면 자동 교체.

실행: python scripts/make_sample_data.py
"""
import json
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[1]
REF, SAMPLE = ROOT / "data" / "ref", ROOT / "data" / "sample"
rng = np.random.default_rng(42)

URBAN_NIGHT = {"연동", "노형동", "이도2동", "일도2동", "삼도1동", "삼도2동", "건입동", "용담1동", "천지동", "중앙동", "동홍동", "이도1동", "일도1동"}
TOURIST = {"애월읍", "한림읍", "조천읍", "구좌읍", "성산읍", "중문동", "안덕면", "표선면", "우도면", "대정읍", "남원읍", "한경면", "예래동"}
EAST = {"일도1동", "일도2동", "이도1동", "이도2동", "삼양동", "봉개동", "화북동", "아라동", "건입동", "조천읍", "구좌읍", "우도면"}


def area_km2(geom):
    # 위경도 → 근사 km² (제주 위도 33.4°)
    lat = 33.4
    return geom.area * (111.32 * math.cos(math.radians(lat))) * 110.57


def build_meta():
    g = json.load(open(REF / "jeju_emd.geojson"))
    rows = []
    for f in g["features"]:
        p = f["properties"]
        geom = shape(f["geometry"])
        emd = p["emd"]
        typ = "도심" if emd in URBAN_NIGHT else "관광" if emd in TOURIST else "주거"
        if p["sgg"] == "서귀포시":
            zone = "서귀포"
        else:
            zone = "동부" if emd in EAST else "서부"
        c = geom.centroid
        rows.append(dict(emd=emd, sgg=p["sgg"], adm_cd2=p["adm_cd2"], type=typ, zone=zone,
                         area_km2=round(area_km2(geom), 2), lon=round(c.x, 5), lat=round(c.y, 5)))
    meta = pd.DataFrame(rows).sort_values(["sgg", "emd"]).reset_index(drop=True)
    meta.to_csv(REF / "emd_meta.csv", index=False)
    return meta


HOLIDAYS = [
    # 2025
    "2025-01-01", "2025-01-28", "2025-01-29", "2025-01-30", "2025-03-03", "2025-05-05", "2025-05-06",
    "2025-06-03", "2025-06-06", "2025-08-15", "2025-10-03", "2025-10-06", "2025-10-07", "2025-10-08",
    "2025-10-09", "2025-12-25",
    # 2026
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18", "2026-03-02", "2026-05-05", "2026-05-25",
    "2026-06-03", "2026-08-17", "2026-09-24", "2026-09-25", "2026-09-26", "2026-10-05", "2026-10-09",
    "2026-12-25",
]


def build_calendar():
    pd.DataFrame({"date": HOLIDAYS, "name": "공휴일"}).to_csv(REF / "holidays.csv", index=False)


def build_events():
    ev = pd.DataFrame([
        dict(date="2026-11-21", emd="삼도2동", name="탑동 야간 문화행사 (예시)", uplift=0.55),
        dict(date="2026-11-22", emd="삼도2동", name="탑동 야간 문화행사 (예시)", uplift=0.40),
        dict(date="2026-11-21", emd="중문동", name="중문 야간 공연 (예시)", uplift=0.20),
        dict(date="2026-11-27", emd="천지동", name="서귀포 야간 시장 행사 (예시)", uplift=0.25),
    ])
    ev.to_csv(SAMPLE / "events.csv", index=False)
    cruise = pd.DataFrame([
        dict(date="2026-11-19", port="강정항", emd="대천동", ships=1),
        dict(date="2026-11-21", port="제주항", emd="건입동", ships=2),
        dict(date="2026-11-24", port="강정항", emd="대천동", ships=1),
    ])
    cruise.to_csv(SAMPLE / "cruise.csv", index=False)
    return ev


def build_night_people(meta, ev):
    start, end = date(2025, 5, 1), date(2026, 11, 16)
    days = pd.date_range(start, end, freq="D")
    hol = set(pd.to_datetime(HOLIDAYS))
    rows = []
    for _, m in meta.iterrows():
        base = {"도심": rng.uniform(14000, 38000), "관광": rng.uniform(5000, 16000), "주거": rng.uniform(4000, 15000)}[m.type]
        if m.emd in ("우도면", "추자면"):
            base = rng.uniform(900, 1800)
        late_share = {"도심": 0.42, "관광": 0.30, "주거": 0.28}[m.type]
        for d in days:
            dow = d.dayofweek
            w = {4: 1.18, 5: 1.22, 6: 0.97}.get(dow, 1.0) if m.type == "도심" else {4: 1.08, 5: 1.12}.get(dow, 1.0)
            season = 1 + (0.18 if m.type == "관광" else 0.07) * math.sin((d.dayofyear - 110) / 365 * 2 * math.pi)
            h = 1.0
            if (d + timedelta(days=1)) in hol:
                h = 1.12 if m.type != "주거" else 1.05
            if d in hol:
                h = max(h, 1.06)
            rain = rng.random() < 0.22
            r = 0.9 if rain else 1.0
            val = base * w * season * h * r * rng.normal(1, 0.05)
            rows.append((d.date().isoformat(), m.emd, round(val), int(rain)))
    df = pd.DataFrame(rows, columns=["date", "emd", "night_people", "rain"])
    df["night_people"] = df["night_people"].astype(float)
    # 지난 행사 효과 예시 (2025 가을 탑동 행사)
    df.loc[(df.emd == "삼도2동") & (df.date.isin(["2025-10-18", "2025-10-19"])), "night_people"] *= 1.3
    df["night_people"] = df["night_people"].round().astype(int)
    df["late_share"] = df.emd.map(dict(zip(meta.emd, meta.type))).map({"도심": 0.42, "관광": 0.30, "주거": 0.28})
    df.to_csv(SAMPLE / "night_people.csv", index=False)
    return df


def build_infra(meta):
    rows = []
    for _, m in meta.iterrows():
        a = max(m.area_km2, 0.5)
        lights_per_km2 = {"도심": rng.uniform(140, 320), "관광": rng.uniform(6, 22), "주거": rng.uniform(25, 110)}[m.type]
        cctv_per_km2 = {"도심": rng.uniform(18, 45), "관광": rng.uniform(0.6, 3.0), "주거": rng.uniform(3, 14)}[m.type]
        if m.emd in ("삼도2동", "건입동", "용담1동"):
            lights_per_km2 *= 0.6  # 예시: 구도심 골목 조명 부족
        rows.append(dict(emd=m.emd, streetlights=int(lights_per_km2 * a), security_lights=int(lights_per_km2 * a * 0.4),
                         cctv=int(cctv_per_km2 * a), road_km=round(a * {"도심": 18, "관광": 3.5, "주거": 7}[m.type], 1)))
    pd.DataFrame(rows).to_csv(SAMPLE / "infra.csv", index=False)


def build_risk():
    # 권역별 인구 10만 명당 5대 범죄 (예시 값, 경찰서별 공개 파일로 교체)
    pd.DataFrame([
        dict(zone="동부", crimes_per_100k=1180),
        dict(zone="서부", crimes_per_100k=1320),
        dict(zone="서귀포", crimes_per_100k=1050),
    ]).to_csv(SAMPLE / "risk_zone.csv", index=False)


def build_visitors():
    days = pd.date_range("2025-05-01", "2026-11-30", freq="D")
    v = [round(42000 * (1 + 0.15 * math.sin((d.dayofyear - 110) / 365 * 2 * math.pi)) * {5: 1.1, 6: 1.05}.get(d.dayofweek, 1) * rng.normal(1, 0.03)) for d in days]
    pd.DataFrame({"date": days.date.astype(str), "visitors": v}).to_csv(SAMPLE / "visitors.csv", index=False)


def build_weather():
    days = pd.date_range("2026-11-17", "2026-11-30", freq="D")
    pop = [20, 10, 60, 70, 20, 10, 30, 30, 50, 20, 10, 10, 40, 20]
    pd.DataFrame({"date": days.date.astype(str), "rain_prob": pop, "tmin": [9, 8, 10, 11, 8, 7, 9, 10, 10, 8, 7, 6, 8, 7],
                  "sunset": ["17:23"] * 14}).to_csv(SAMPLE / "weather_forecast.csv", index=False)


if __name__ == "__main__":
    meta = build_meta()
    build_calendar()
    ev = build_events()
    build_night_people(meta, ev)
    build_infra(meta)
    build_risk()
    build_visitors()
    build_weather()
    print("예시 저장본 생성 완료:", len(meta), "개 읍면동")
