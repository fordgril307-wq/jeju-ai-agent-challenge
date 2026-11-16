# 제주 AI·빅데이터 활용 AI Agent 개발 챌린지 — 팀 작업 저장소

- 대회: 제주 AI·빅데이터 활용 AI Agent 개발 챌린지 (주최 제주테크노파크, DAKER)
- 제출 마감: 2026-11-20(금) 10:00
- 대회 페이지: https://daker.ai/public/hackathons/jeju-ai-bigdata-agent-challenge

## 지금 할 일 (11/16 중)
주제 결정 — 1안 · 2안 · 결합 중 선택. 결정 직후 11/17(화) 오전 제주빅데이터센터 반출 신청.

| 안 | 주제 | 1차 타깃 | 데이터 |
|---|---|---|---|
| 1안 | 쓰레기 예보관 — 생활·관광폐기물 7일 배출 예보, 수거 증편 계획 | 시·행정시 청소 담당 부서 | 55종 (예보 대상은 센터 원본 반출 가능) |
| 2안 | 밤길 안심 예보관 — 야간 안전 수요 7일 예보, 순찰·조명 우선순위 | 제주자치경찰단 순찰 계획 담당 | 32종 (센터는 밤 인원, 위험·시설은 공개 데이터) |

## 자료조사
- 📄 [docs/topic-research-brief_v4.pdf](docs/topic-research-brief_v4.pdf) — 57쪽, 두 안 동일 구조 (문제 · 타깃층 · 데이터 · 에이전트 활용 · 시연 · 기대효과 · 차별화·위험), 추천 없는 비교, 데이터·기사 출처 포함
- 이전 자료: [docs/team-brief_topic-selection.pdf](docs/team-brief_topic-selection.pdf) (11/6, 탐나는전 vs 쓰레기)

## 시연 (숫자는 모두 예시 값)
| 파일 | 내용 | 바로 보기 |
|---|---|---|
| [demo/waste-agent.html](demo/waste-agent.html) | **1안 에이전트 시연** — 목표 한 줄 → 되묻기 → 계획 → 도구 호출(실패 시 저장본 우회) → 지난 4주 자기 검증 → 증편 계획서·업체 문자·다국어 안내문·반출 신청서 → 담당자 승인 | [열기](https://htmlpreview.github.io/?https://github.com/fordgril307-wq/jeju-ai-agent-challenge/blob/main/demo/waste-agent.html) |
| [demo/night-safety.html](demo/night-safety.html) | 2안 시연판 — 7일 야간 안전 수요 예보, 순찰·조명 권고, 범죄율 팩트체크(이 표만 실제 공개 수치) | [열기](https://htmlpreview.github.io/?https://github.com/fordgril307-wq/jeju-ai-agent-challenge/blob/main/demo/night-safety.html) |
| [demo/waste-forecast-board.html](demo/waste-forecast-board.html) | 1안 초기 예보판 (참고용) | [열기](https://htmlpreview.github.io/?https://github.com/fordgril307-wq/jeju-ai-agent-challenge/blob/main/demo/waste-forecast-board.html) |

'열기'가 안 되면 파일을 내려받아 브라우저로 열기.

## 유의
- 대회에서 받은 '제주데이터허브 데이터 목록 xlsx'는 외부 배포 금지 → 이 저장소에 올리지 않음
- API 키 등 비밀값 커밋 금지
- 결과물은 대회 규정상 제주빅데이터센터 귀속
