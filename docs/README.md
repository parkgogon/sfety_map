# v3 재설계 문서

이 디렉터리는 제품 목표와 업무 규칙을 먼저 확정하고, 검증된 기능만 가져와
재구축한 v3의 변경 기준입니다.

문서는 다음 순서로 읽습니다.

0. [HANDOFF.md](HANDOFF.md) — 새 작업자가 실제 Git·코드와 대조할 현재 상태와 다음 작업
0. [IMPROVEMENT_ROADMAP.md](IMPROVEMENT_ROADMAP.md) — 운영형 구조로 단계적으로 개선하는 확정 로드맵
1. [PRODUCT.md](PRODUCT.md) — 누구를 위해 어떤 문제를 해결하는가
2. [FEATURE_INVENTORY.md](FEATURE_INVENTORY.md) — 무엇을 유지·변경·제외할 것인가
3. [DOMAIN_RULES.md](DOMAIN_RULES.md) — 같은 입력이 항상 같은 결과를 내도록 하는 규칙
4. [UI_FLOW.md](UI_FLOW.md) — 정보가 어디에 한 번만 나타나고 사용자가 어떻게 행동하는가
5. [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md) — 역할별 화면을 하나의 제품으로 유지하는 표현 규칙
6. [ARCHITECTURE.md](ARCHITECTURE.md) — 위 내용을 변경하기 쉬운 코드로 만드는 방법
7. [FIELD_MAP_DEPLOYMENT.md](FIELD_MAP_DEPLOYMENT.md) — React 현장 지도와 서울 API 실행·배포

## 문서 상태 표기

- **확정**: 기존 데이터 또는 구현 근거가 충분하며 v3 기준으로 채택
- **제안**: 현재 권장안이며 사용자 확인 후 확정
- **결정 필요**: 제품 방향을 바꿀 수 있어 임의로 확정하지 않음
- **보류**: v3 첫 배포 범위 밖

제품 범위·관제 권역·위험도 정책 결정은 확정됐으며, 핵심 도메인 예제는
`tests_v3/`에서 자동 검증합니다.

AI 서비스나 작업 세션을 바꿀 때는 저장소 루트의 [`AGENTS.md`](../AGENTS.md)를
먼저 읽고 이 디렉터리의 `HANDOFF.md`를 실제 Git 상태와 대조합니다.
`HANDOFF.md`는 작업일지를 누적하는 문서가 아니라 현재 완료·미완료·다음 작업을
유지하는 살아 있는 상태 문서입니다.
