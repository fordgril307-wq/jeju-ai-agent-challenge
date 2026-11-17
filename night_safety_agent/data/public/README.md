# 공개 데이터 넣는 곳

허브·공공데이터포털에서 내려받아 같은 열 이름으로 정리한 CSV를 두면 예시 저장본 대신 자동 사용.
우선순위: data/center → data/public → data/sample(예시)

| 파일명 | 필수 열 | 원천 |
|---|---|---|
| night_people.csv | date, emd, night_people | 제주데이터허브 「읍면동 단위 내국인 유동인구」 API (일 합계 × 밤 비중 가정) |
| infra.csv | emd, streetlights, cctv | 제주시 가로등 현황(포털 15129786), 전국 CCTV·보안등 표준데이터 |
| risk_zone.csv | zone, crimes_per_100k | 제주경찰청 5대 범죄 발생 현황(포털 15123527) |
| events.csv | date, emd, name, uplift | 한국관광공사 TourAPI 행사 정보 |
| cruise.csv | date, port, emd, ships | 제주도 크루즈 입항 일정 |
| visitors.csv | date, visitors | 한국관광공사 지역별 방문자수(포털 15101972) |
| weather_forecast.csv | date, rain_prob (선택: tmin, sunset) | 기상청 단기·중기예보, 한국천문연구원 출몰시각 |
