# 센터 데이터 넣는 곳 (센터 PC 전용)

제주빅데이터센터 PC에서 아래 이름·열로 집계한 CSV를 이 폴더에 두면 예시 저장본 대신 자동 사용.
센터 데이터는 센터 밖으로 반출하지 않음 — 이 폴더 내용은 저장소·제출물에 포함 안 됨.

| 파일명 | 필수 열 | 만드는 방법 |
|---|---|---|
| night_people.csv | date, emd, night_people (선택: rain, late_share) | 4-11·4-13·4-15 유동인구에서 21~24시 + 다음 날 0~3시 합계를 읍면동·날짜별로 집계, late_share = 0~3시 비중 |
| infra.csv | emd, streetlights, cctv (선택: security_lights, road_km) | 3-07 도로 구간 길이 합계(road_km) + 공개 가로등·CCTV 좌표 읍면동 집계 |

10 미만 값은 화면·보고서 출력 시 반출 검사 도구가 자동으로 '10 미만' 처리.
