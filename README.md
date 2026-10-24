# 기상재난 시설 안전관제

대구·경북·부산·울산·경남 소관시설 195개소를 KMA 공식 기상특보와 대조해
영향 시설과 점검 우선순위를 표시하는 내부 시범 운영 시스템입니다.

- 현장 안전지도 `/`: Kakao 지도, 시설 검색·필터·상세, 임시 기준점과 주변 시설 거리 비교
- 중앙관제 `/control`: 운영 상황, 대상 분석·수동 상황전파, 실적·이력과 PDF 보고
- 위험도 정책 `/settings`: 관리자 인증 후 브라우저 세션에만 적용하는 정책표 편집

화면은 React·TypeScript, 서버는 Python FastAPI입니다. Firebase Hosting에서
Cloud Run API로 요청하며, 별도 Worker가 5분마다 특보 변화를 감시합니다.
Streamlit과 구버전 점수식 구현은 제거했습니다.

## 로컬 실행

Python 3.12와 Node.js 20.19 이상을 사용합니다.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

`.env`에 로컬 KMA 키와 관리자 비밀번호를 입력합니다. 운영 API·Worker는
Secret Manager에서 주입한 환경변수를 사용합니다. 기존 Streamlit secrets 파일은
읽지 않습니다. 실제 키·전화번호·비밀번호는 Git에 넣지 않습니다.

```bash
.venv/bin/uvicorn safety_dashboard.api.app:app --env-file .env --host 127.0.0.1 --port 8080
```

별도 터미널에서 웹을 실행합니다.

```bash
cd field_web
npm ci
cp .env.example .env.local
npm run dev
```

`.env.local`에는 Kakao **JavaScript 키**를 입력하고, Kakao 개발자 콘솔에
`http://localhost:5173`을 등록합니다. API 경로는 Vite가 로컬 8080으로 전달합니다.
CCTV는 기본 예제와 운영 배포 모두 비활성 상태입니다.

## 코드 구조

```text
field_web/src/                 React 화면·지도·프런트엔드 디자인 토큰
safety_dashboard/domain/       시설·특보 모델, 위험도 정책과 지역 매칭
safety_dashboard/application/  조회·선택·메시지 유스케이스
safety_dashboard/api/          공개·관리자 HTTP API와 조회 서비스
safety_dashboard/alerts/       변화 감지·중복 방지·자동알림·운영보고
safety_dashboard/adapters/     KMA·Firestore·Telegram·SOLAPI·PDF 연동
safety_dashboard/monitoring/   공통 관제 snapshot 계약
safety_dashboard/config/       위험도·시설 그룹 설정과 환경변수 접근
facilities_info.csv            운영 시설 데이터의 단일 기준
tests/                         현행 Python 회귀 테스트
scripts/                       안전한 검증 명령과 운영 도구
```

시설은 시설 ID로 식별합니다. 위험도는 특보 종류 × 단계 정책표를 사용하며,
여러 특보 중 가장 높은 등급을 적용합니다. 기준표는
[safety_dashboard/config/risk_policy.toml](safety_dashboard/config/risk_policy.toml),
시설 유형 7개 그룹은
[safety_dashboard/config/facility_groups.toml](safety_dashboard/config/facility_groups.toml)에서 관리합니다.

## 검증

```bash
bash scripts/verify_all.sh
```

Python 검증만 실행할 때도 외부 통신을 차단하는 공통 진입점을 사용합니다.

```bash
.venv/bin/python scripts/run_python_tests.py
```

실제 Telegram·SMS 시험 발송은 하지 않습니다. Python 테스트는 실제 HTTP·TCP를
차단하고, React 테스트는 가짜 API가 빠진 HTTP 요청을 실패시킵니다. 수동전파와
부분 실패·재시도는 가짜 제공자·메모리 저장소로 검증합니다. 브라우저 전파 검수도
가짜 API에서만 수행하고 운영방·운영 전파/Worker 시험 경로를 호출하지 않습니다.

## 운영과 문서

`main` push는 GitHub Actions의 검증 후 API·Worker·Firebase 운영 배포로 이어집니다.
커밋·push·배포는 사용자 요청에 따라 별도로 수행합니다.

새 작업자는 [AGENTS.md](AGENTS.md), [현재 상태](docs/HANDOFF.md),
[구조 개선 계획](docs/archive/REFACTORING_PLAN_20261024.md)을 먼저 읽고 실제 코드와 Git을 대조합니다.
[아키텍처](docs/ARCHITECTURE.md), [업무 규칙](docs/DOMAIN_RULES.md),
[자동알림](docs/AUTOMATIC_ALERTS.md), [배포 안내](docs/FIELD_MAP_DEPLOYMENT.md)를 함께 참고합니다.
