# 현재 아키텍처

기준: 2026-10-24 구조 개선 1~5단계 코드 반영. React가 현장·중앙관제·설정의 유일한 UI이며
Streamlit과 루트 구버전 구현은 제거했습니다. API와 Worker는 하나의 코드베이스를
공유하는 모듈형 모놀리스입니다.

## 실행 구조

```text
Firebase Hosting / React SPA / Kakao Maps
  /                 현장 안전지도
  /control          중앙관제
  /settings         위험도 설정
          │ /api/**, /internal/**
          ▼
Cloud Run API (서울 asia-northeast3)
  공개 조회·관리자 세션·수동전파·PDF·정책
          │
          ├── Firestore: MonitoringSnapshot, 상태·발송·outbox·실적·감사
          ├── KMA 공식 특보·경계·실황
          ├── Telegram / 선택형 SOLAPI
          └── PDF·정적 지도
          ▲
Cloud Run Worker ← Cloud Scheduler (5분, OIDC)
```

세 React 화면은 정적 import 단일 번들로 배포합니다. 초기 lazy 청크를 합친 이유는
화면 이동 시 이전 배포 청크가 섞이는 문제였으며, 다시 나누려면 HTML 캐시와 배포
중 청크 교체를 함께 검증해야 합니다. HTML은 재검증·저장 금지 정책을 사용합니다.

## 책임 경계

- `domain`: 시설 ID·좌표, 특보, 위험도·등급·근거, 지역 매칭. UI·외부 HTTP에 의존하지 않습니다.
- `application`: snapshot 구성, 조회/작업 대상 선정, 정책 재평가, 전파 문안 구성.
- `adapters`: KMA·CSV·공식 경계·Firestore·Telegram·SOLAPI·PDF 등 외부 기술.
- `api`: 조립 진입점, 공통 서비스 생성, 요청 모델·인증 경계, 업무별 라우터, 조회 캐시.
  라우터는 health·admin·monitoring·context·notifications·reports·policy로 구분합니다.
- `alerts`: 5분 회차, 발효·격상·해제 감지, 중복 방지, 전달·재시도와 운영 상태 보고.
- `monitoring`: 공통 MonitoringSnapshot의 직렬화·검증·저장 인터페이스.
- `operations` / `admin`: 운영 준비 상태, 관리자 비밀번호·서명 세션.
- React는 API에서 받은 동일한 평가 결과를 표시합니다. 인증·현장 상태 훅과 중앙관제
  화면을 분리했고, 지도 런타임·레이어는 `field_web/src/map/`에서 관리합니다.
  디자인 토큰과 영역별 CSS는 프런트엔드가 소유합니다.

## 공통 관제 결과와 장애

Worker는 정상 회차에 최신 `MonitoringSnapshot`과 latest 포인터를 원자적으로 저장합니다.
API는 정상·정책 일치·15분 이내 저장본을 우선 사용하고 필요하면 KMA를 직접 조회합니다.

snapshot에는 ID·스키마 버전·생성/조회 시각·정책 버전·자료 상태를 보존하며,
연락처와 내부 메타데이터는 공개 전송·Firestore snapshot에서 제거합니다.

KMA 실패 시 마지막 정상 특보와 기준 상태를 보존하고 STALE로 표시합니다.
사용 가능한 자료가 없으면 ERROR/조회 불가로 표시하며 정상 0건으로 바꾸지 않습니다.
STALE·ERROR 자료에서는 새 수동전파·PDF를 생성하지 않습니다. 훈련은 실시간
snapshot·캐시·자동알림 기준 상태와 분리합니다.

## 자동알림과 저장

- `AlertCyclePlanner`: snapshot과 이전 상태에서 영향·변화 계획을 계산하는 순수 로직.
- `AlertDispatcher`: 회차 잠금과 전체 실행 순서.
- `SmsDeliveryService`: 연락처·비용 상한·SMS와 Telegram 대체 전달.
- `TelegramOutboxService`: 관리자/시설담당자 전달·부분 실패·제한 시간 재시도.
- `AlertOperationsService`: 잔액 점검과 09/18시 운영보고.
- `MonitoringHealthService`: KMA 장애·복구 진단/상태와 공통 snapshot 저장 상태.
- `FirestoreAlertStore`: 상태·SMS·Telegram outbox·감사 저장소를 감싼 호환 facade.

자동알림은 발효·격상·해제만 전파합니다. 무변화 반복 발송은 하지 않습니다.
필터·정책·모드 변경 시 현재 활성 특보를 새 사건처럼 재발송하지 않도록 기준화를 유지합니다.
KMA 장애는 해제가 아니며 기준 상태를 갱신하지 않습니다.

보류·outbox 조회는 `status == PENDING` 조건을 사용합니다. 완료·만료 문서에만
7일 보존용 `delete_after`를 기록하고 Firestore TTL 정책은 배포 안내를 따릅니다.
저장 포트도 상태·발송·outbox·감사로 나누고 기존 `AlertStateStore` 통합 계약은 유지합니다.
SMS와 운영보고는 필요한 포트 조합만 받습니다. 컬렉션 이름·문서 ID·중복 방지 키·
상태 스키마는 이번 구조 개선에서 바꾸지 않습니다.

## HTTP·보안·출력 계약

공개 경로는 `/api/v1`, 보호된 관리자 경로는 `/internal/v1`입니다.
관리자 비밀번호는 서버에서 검증하고 8시간 HMAC 서명 세션을 HttpOnly 쿠키로 발급합니다.
관리자 토큰 헤더의 기존 호환 방식도 유지합니다. 인증 경로는 비밀번호를 응답하지 않고
실패 제한·만료·로그아웃과 감사 기록을 유지합니다.

수동전파는 분류·훈련 표시·최종 대상·중복 확인과 감사 기록을 보존합니다.
자동·수동·시험·훈련 실적을 분리합니다. PDF는 관제 snapshot을 그대로 사용하고
별도 위험도 계산을 하지 않습니다. 공개 PDF와 관리자 PDF 경로를 모두 유지합니다.

현재 기상·기상 그래픽·임시 기준점 거리·뉴스·CCTV는 참고정보입니다.
위험도·자동알림 기준·수동전파 대상·PDF 평가에 혼합하지 않습니다.
CCTV는 코드·테스트를 유지하지만 운영 플래그는 비활성입니다.

## 설정·검증·운영

서버 설정은 환경변수로 읽고 운영 비밀값은 Secret Manager에서 주입합니다.
로컬 `.env`와 웹 `.env.local`은 Git에서 제외합니다. Streamlit secrets fallback은 제거했습니다.
API·Worker 실행 진입점과 기존 환경변수 이름·기본값은 유지합니다.

Python 검증은 `scripts/run_python_tests.py`, 전체 검증은 `scripts/verify_all.sh`입니다.
실제 외부 HTTP·TCP를 차단하고 Telegram·SMS는 가짜 제공자로만 검증합니다.
브라우저 전파 검수도 운영 API를 호출하지 않는 가짜 API 환경에서 수행합니다.

운영 로그에는 키·전화번호·외부 원문을 기록하지 않습니다. Cloud Logging·Monitoring과
예산 알림을 사용하고, 참고정보 제공자 실패와 전체 API 장애를 구분합니다.
`main` push에 운영 배포가 연결되므로 별도 사용자 요청 시에만 push·배포합니다.

현재 상태는 [인수인계](HANDOFF.md), 완료한 단계와 수용 조건은
[구조 개선 기록](archive/REFACTORING_PLAN_20261024.md)을 따릅니다.
