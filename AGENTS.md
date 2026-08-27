# 프로젝트 작업·인수인계 지침

이 파일은 특정 AI 서비스에 종속되지 않는 프로젝트 운영 지침입니다. 사람 또는
AI가 처음 작업을 맡으면 이 파일과 [`docs/HANDOFF.md`](docs/HANDOFF.md)를 먼저
읽습니다. 자동으로 `AGENTS.md`를 읽지 않는 도구에는 사용자가 두 파일을 읽으라고
한 번만 지시하면 됩니다.

## 1. 시작 절차

문서만 믿고 바로 수정하지 않습니다. 다음 순서로 현재 상태를 복구합니다.

1. `AGENTS.md`를 끝까지 읽습니다.
2. `docs/HANDOFF.md`의 `현재 상태`, `진행 중인 개선`, `다음 작업`을 읽습니다.
3. 아래 명령으로 문서와 실제 저장소를 대조합니다.

   ```bash
   git branch --show-current
   git status --short
   git diff --stat
   git diff --cached --stat
   git log -8 --oneline --decorate
   ```

4. 요청과 관련된 코드·테스트·설계 문서를 직접 읽습니다.
5. handoff와 코드가 다르면 코드·테스트·Git을 우선하고, 차이를 사용자에게 알린
   뒤 handoff를 바로잡습니다.
6. 운영 상태가 작업 판단에 중요할 때만 공개 health 또는 보호된 관리자 API를
   읽기 전용으로 확인합니다. 비밀값이나 외부 응답 원문을 출력하지 않습니다.

## 2. Source of truth 우선순위

충돌할 때는 다음 순서를 사용합니다.

1. 실제 코드, 자동 테스트, 배포 설정과 검증된 운영 상태
2. 현재 프로젝트 파일과 Git working tree/commit 이력
3. 현재 사용자의 최신 요구사항
4. `docs/HANDOFF.md`의 살아 있는 현재 상태
5. `docs/`의 제품·도메인·설계 문서
6. 과거 대화나 AI의 기억

`docs/PRODUCT.md`와 `docs/FEATURE_INVENTORY.md`에는 v3 초기 범위의 역사적 문구도
남아 있습니다. 현재 구현 여부는 handoff, 코드, 테스트를 함께 확인합니다.

## 3. 프로젝트 목적과 제품 경계

대구·경북·부산·울산·경남의 소관시설 103개소를 KMA 공식 기상특보와 대조해
영향 시설과 점검 우선순위를 보여주고, 시설담당자 알림과 중앙관제 보고를 돕는
내부 시범 운영 시스템입니다.

핵심 원칙은 다음과 같습니다.

- 시설담당자는 스마트폰 지도에서 원하는 시설을 빠르게 선택해 확인합니다.
- 중앙관제는 전체 영향시설을 분석하고 수동 상황전파와 PDF 보고를 수행합니다.
- 위험도는 설명 가능한 `특보 종류 × 단계` 정책표를 사용합니다.
- 현재 기상·기상 그래픽·CCTV·뉴스 등 참고정보는 위험도에 섞지 않습니다.
- 장애를 `특보 없음` 또는 `안전`으로 표현하지 않습니다.
- 시험·훈련·수동·자동 실적을 서로 구분합니다.

제품 상세는 다음 문서를 필요한 만큼 읽습니다.

- 제품 의도: `docs/PRODUCT.md`
- 현재 업무 규칙: `docs/DOMAIN_RULES.md`
- UX와 디자인: `docs/UI_FLOW.md`, `docs/DESIGN_SYSTEM.md`
- 구조: `docs/ARCHITECTURE.md`
- 자동 알림 운영: `docs/AUTOMATIC_ALERTS.md`
- 배포: `docs/FIELD_MAP_DEPLOYMENT.md`
- 단계별 개선: `docs/IMPROVEMENT_ROADMAP.md`

## 4. 현재 아키텍처 지도

```text
Firebase Hosting / React / Kakao Maps
  field_web/                    시설담당자용 현장 안전지도
          │ /api/**
          ▼
Cloud Run API
  safety_dashboard/api/         공개 조회와 보호된 관리자 API
  safety_dashboard/domain/      외부 기술과 무관한 모델·위험도
  safety_dashboard/application/ 조회·선택·메시지 유스케이스
  safety_dashboard/adapters/    KMA·CSV·Firestore·Telegram·PDF 등
          ▲
          │ 공통 MonitoringSnapshot
          ▼
Cloud Run Worker + Scheduler
  safety_dashboard/alerts/      5분 자동감시·변화·발송·운영보고

Streamlit (전환 기간 관리자 UI)
  app.py
  safety_dashboard/ui/pages/    현장 지도·중앙 관제·설정
```

실행 단위는 API와 Worker로 나뉘지만, 코드는 **모듈형 모놀리스**로 유지합니다.
KMA·Telegram·PDF 등을 각각 서버로 분해하는 MSA는 현재 규모에서 운영 복잡도가 더
크므로 도입하지 않습니다.

루트의 `core/`, `data_providers/`, `services/`, `ui/`, `risk_engine.py`,
`report_generator.py`, `telegram_utils.py`는 아직 회귀 테스트가 남아 있는 구버전
영역입니다. 현행 패키지로 기능과 테스트를 옮기기 전에는 삭제하지 않습니다.

## 5. 변경 시 지켜야 할 불변 규칙

- KMA 조회 실패를 특보 해제로 해석하지 않습니다. 마지막 정상 상태를 보존합니다.
- 자동알림 기준 상태를 임의로 초기화하거나 현재 발효 특보를 재전파하지 않습니다.
- 정책·필터·전달 경로 변경 시 기준 상태 처리와 중복 방지를 먼저 검토합니다.
- 사용자 지도, 중앙관제, 자동알림과 PDF는 가능한 한 같은 관제 snapshot을
  사용합니다.
- `STALE`·`ERROR` 자료로 새 수동 Telegram이나 PDF를 만들지 않습니다.
- 실시간 자료, 모의훈련, 브라우저 임시 위험도 정책을 섞지 않습니다.
- 시설 ID가 식별자입니다. 시설명이나 좌표만으로 동일 시설을 가정하지 않습니다.
- 전화번호는 화면·PDF·Telegram·로그·Firestore에 원문으로 남기지 않습니다.
- Telegram 관리자방과 시설담당자 그룹의 목적을 섞지 않습니다.
- 자동알림은 발효·격상·해제 변화 기반입니다. 정상 무변화 상태를 반복 발송하지
  않습니다.
- `열대야`는 현재 자동알림 제외 기본값입니다. 지도와 위험도 자체에서 제거하는
  것은 아닙니다.
- CCTV는 코드가 있어도 운영 배포에서 비활성입니다. 네트워크 경로와 비용을
  해결하고 실사용 검증하기 전에는 켜지 않습니다.
- React 중앙관제가 기능 동등성을 확보하기 전에는 Streamlit 중앙관제를 제거하지
  않습니다.
- 공용 관리자 비밀번호는 임시 보호수단입니다. 비밀번호나 API 토큰을 브라우저
  번들에 넣지 않습니다.

## 6. 사용자 의도와 작업 방식

- 사용자는 기술 용어보다 결과와 선택의 영향을 쉬운 한국어로 설명받는 것을
  선호합니다.
- 외부 서비스 설정은 한 번에 긴 목록을 주기보다 한 단계씩 안내하고 확인합니다.
- 시설담당자의 담당 시설은 자주 바뀌므로 영구적인 `내 시설 묶음` 기능을 만들지
  않습니다. 검색·필터로 원하는 시설을 선택하는 흐름을 유지합니다.
- 스마트폰 현장 지도는 지도와 선택 시설 정보가 중심입니다. 보고·수동 전파 같은
  관리자 작업을 현장 화면에 섞지 않습니다.
- 코드가 복잡해졌다고 전면 재작성하거나 MSA로 분해하지 않습니다. 회귀 테스트를
  유지하며 작은 책임 단위로 점진적으로 분리합니다.
- 시범 프로젝트이므로 불필요한 월 고정비와 과도한 인프라를 피합니다.
- 운영 링크가 내부 공유용이어도 secret을 Git에 커밋하지 않습니다.

## 7. 안전한 작업 규칙

- 기존 dirty working tree와 사용자 산출물을 보존합니다. 현재 `output/`, `tmp/`는
  untracked 사용자/보고자료 작업공간이므로 요청 없이 삭제·추가·커밋하지 않습니다.
- `.streamlit/secrets.toml`, `field_web/.env.local`, 전화번호 명부와 Secret
  Manager 값은 읽더라도 출력·복사·커밋하지 않습니다.
- 앱 기능 변경은 요청 범위에만 한정하고, 관련 없는 파일을 정리한다는 이유로
  함께 수정하지 않습니다.
- `main` push는 GitHub Actions를 통해 운영 API·웹·Worker 배포로 이어질 수
  있습니다. 사용자가 push/배포를 요청했는지 확인합니다.
- 자동알림 `live` 상태에서 시험할 때 운영 기준 상태와 실적을 바꾸지 않는 전용
  시험 경로와 가짜 provider를 사용합니다.

## 8. 검증 명령

변경 위험에 맞게 실행하되, 서버·공통 로직을 바꾼 경우 전체 검증을 권장합니다.

```bash
.venv/bin/python -m safety_dashboard.api.validate_data
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
.venv/bin/python -m unittest discover -s tests_v3 -p 'test_*.py'
.venv/bin/python -m compileall -q app.py safety_dashboard core
cd field_web && npm test && npm run build
```

운영 전송은 자동 테스트에서 실행하지 않습니다. 외부 시험은 사용자의 명시적 요청과
시험 대상 확인 후 수행합니다.

## 9. 작업 종료와 handoff 갱신

중요한 기능·구조·운영 설정·의사결정이 바뀐 경우에만 `docs/HANDOFF.md`를
갱신합니다. 사소한 CSS 수정이나 커밋 목록을 작업일지처럼 누적하지 않습니다.

종료 전에 다음을 수행합니다.

1. `git status`, `git diff`, 관련 테스트 결과를 확인합니다.
2. 완료한 일과 실제 미완료를 `docs/HANDOFF.md`에서 현재형으로 교체합니다.
3. 새 결정 또는 폐기된 방향이 있으면 `사용자 의도와 확정 결정`을 수정합니다.
4. `다음 작업`은 한 개의 명확한 시작점과 수용 조건으로 유지합니다.
5. 장기 로드맵 체크 상태가 바뀌면 `docs/IMPROVEMENT_ROADMAP.md`도 갱신합니다.
6. 운영 상태처럼 시간이 지나면 낡는 정보에는 확인 날짜를 붙입니다.
7. 비밀값, 개인 연락처, 채팅 초대 링크와 운영 토큰은 기록하지 않습니다.

handoff가 너무 길어지면 오래된 완료 내역을 압축하거나 기존 설계 문서 링크로
대체합니다. 목표는 과거 기록 보존이 아니라 **다음 작업자가 현재 상태를 정확히
복구하는 것**입니다.
