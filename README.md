# 스마트 기상·재난 관제 대시보드

대구경북환경본부 소관시설 권역(대구·경북·부산·울산·경남)의 기상특보,
시설 영향도와 점검 우선순위 목록을 조회하고, Telegram 요청과 PDF 보고서를 만드는
Streamlit 대시보드입니다.

## 실행

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

`.streamlit/secrets.toml`에 KMA API 키와 텔레그램 설정을 입력해야 합니다.
실제 비밀정보 파일은 Git에서 제외됩니다.

시설담당자용 React 현장 지도 1차 화면은 `field_web/`, 같은 위험도 계산을
제공하는 Cloud Run API는 `safety_dashboard/api/`에 있습니다. 기존 Streamlit
화면과 병행 검증하며 로컬 실행·Firebase/Cloud Run 자동 배포 준비는
[`docs/FIELD_MAP_DEPLOYMENT.md`](docs/FIELD_MAP_DEPLOYMENT.md)를 따릅니다.

Telegram 시설 딥링크를 사용하려면 `[dashboard].base_url`에 운영 중인
HTTPS 대시보드 주소를 설정합니다. 행정안전부 재난문자는
재난안전데이터공유플랫폼에서 `행정안전부_긴급재난문자`를 활용 신청한 뒤
`[safety_data].api_key`를 설정하면 활성화됩니다. 키가 없어도 나머지 관제 기능은
정상 동작합니다. 설정은 `DASHBOARD_BASE_URL`, `SAFETY_DATA_API_KEY`,
`SAFETY_DATA_API_URL` 환경변수로도 지정할 수 있으며 환경변수가 secrets보다 우선합니다.

ITS 인근 도로 CCTV는 [국가교통정보센터 CCTV Open API](https://its.go.kr/opendata/opendataList?service=cctv)
인증키를 발급받은 뒤 아래 설정을 추가하면 활성화됩니다.
현재 `.streamlit/secrets.toml`은 자동으로 수정하지 않습니다.

## 자동 재난특보 알림

공식 KMA 특보의 발효·격상·해제를 5분마다 감지해 시설담당자에게
알린다. 기본은 사용자 Telegram 비공개 채널이며,
필요할 때만 SOLAPI 문자 우선 모드로 바꾸고 문자 실패 시 Telegram으로
대체 전파한다. KMA·발송·장애 상태는 별도 관리자 Telegram방에 보낸다.
초기 상태는 실제 자동 발송이 없는 `preview`다. 계정·권한·채널·연락처
형식과 운영 전환 순서는
[`docs/AUTOMATIC_ALERTS.md`](docs/AUTOMATIC_ALERTS.md)를 참고한다.

```toml
[its_cctv]
api_key = "YOUR_ITS_CCTV_API_KEY"
api_url = "https://openapi.its.go.kr:9443/cctvInfo"
```

`ITS_CCTV_API_KEY`, `ITS_CCTV_API_URL` 환경변수도 지원하며 환경변수가
secrets보다 우선합니다. 키가 없어도 나머지 관제 기능은 정상 동작합니다.
React 운영 화면의 CCTV는 Cloud Run에서 ITS로의 연결 제한이 확인되어
현재 `CCTV_ENABLED=false`, `VITE_CCTV_ENABLED=false`로 보류한 상태입니다.
고정 출구 IP 또는 국내 중계 경로가 준비되면 코드 변경 없이 두 설정을
`true`로 바꾸어 다시 활성화할 수 있습니다.

## v3 주요 구조

```text
safety_dashboard/domain/       외부 기술에 독립적인 모델과 위험도 정책
safety_dashboard/application/  조회 snapshot과 Telegram 메시지 유스케이스
safety_dashboard/adapters/     KMA·CSV·특보구역·Telegram·PDF 연동
safety_dashboard/ui/pages/     현장 지도·중앙 관제·설정 페이지
safety_dashboard/ui/           공통 컨텍스트·지도·디자인 토큰·외부 CSS
safety_dashboard/config/       사람이 수정하는 위험도 기준표
safety_dashboard/api/          React용 `/api/v1` HTTP API
field_web/                      카카오 지도 기반 모바일 React 현장 화면
app.py                         Streamlit Cloud용 3페이지 라우터
tests_v3/                      v3 핵심 규칙 테스트
```

`app.py`는 배포 설정을 유지하면서 `현장 지도`, `중앙 관제`, `설정`을
상단 메뉴로 연결합니다. 선택한 페이지만 실행되며 공통 관제 입력은 캐시를 공유합니다.

제품 목표, 업무 규칙과 구조는 [`docs/`](docs/README.md)에 정리되어 있습니다.
색상·간격·컴포넌트·역할별 화면 기준은
[`docs/DESIGN_SYSTEM.md`](docs/DESIGN_SYSTEM.md)와
[`safety_dashboard/ui/design_tokens.css`](safety_dashboard/ui/design_tokens.css)를 단일 기준으로 사용합니다.

기본 위험도 기준은
[`safety_dashboard/config/risk_policy.toml`](safety_dashboard/config/risk_policy.toml)에서
특보별 `ADVISORY`, `WARNING`, `CRITICAL` 값을 수정합니다. 값을 바꾸면 반드시
`policy.version`도 함께 올려 보고서가 어떤 기준을 사용했는지 식별할 수 있게 합니다.
상단 `설정` 메뉴에서도 전체 특보 행렬을 편집할 수 있으며,
이 경우는 파일을 바꾸지 않고 현재 브라우저 세션에만 적용됩니다.

`현장 지도`는 전체 시설을 지도 중심으로 보여주며 시설명·주소 검색과 유형 필터를
제공합니다. React 현장 화면은 시설 선택 250ms 후 해당 KMA 격자의
현재 기상을 자동 조회하고, 인근 도로 CCTV는 사용자가 요청할 때만
조회합니다. 둘 다 위험도·Telegram·PDF에는 반영하지 않는 참고정보입니다.
모바일 현장 지도는 기본 조작 가능하며 지도 안의 `페이지 스크롤 우선`으로 전환합니다.

`중앙 관제`는 `운영 상황 / 대상 분석·전파 / 실적·이력`으로 나뉘며,
선택한 화면만 실행됩니다. 시설 유형·지도 표시 등급은 분석 화면의
`조회 범위 변경` popover에서 여러 개를 바꾼 뒤
`조회 범위 적용`을
눌러야 지도와 지표에 반영됩니다. 후속 작업 표의 체크 변경도
사용자 채널 수동 전파 또는 PDF 버튼을 누를 때 한 번에 확정됩니다.
중앙관제 모바일에서는 점검 우선순위 목록을 지도보다 먼저 표시하고, 지도를 기본
잠금해 한 손가락 페이지 스크롤을 유지합니다. 지도 내부의 `지도 조작 켜기`로
필요할 때만 이동·확대를 활성화합니다.
시설 상세 정보와 후속 작업 대상은 PC·모바일 모두 기본으로 접혀 있으며,
필요할 때 펼쳐 판정 근거를 확인하거나 작업 대상을 편집합니다.

수동 상황전파는 관리자 API를 거쳐 사용자 Telegram 채널로 발송하며
`재공지·정정·추가안내·훈련` 분류와 감사 기록을 남깁니다. 메시지는
요약과 등급별 시설 상세를 나누어 발송합니다.
상·미판정 시설이 있을 때만 요약을 일반 알림으로 보내고 상세는 무음으로
보냅니다. 시설명 링크는 해당 시설을 지도에서 바로 표시합니다.
시설 상세의 인근 도로 CCTV, 최근 6시간 재난문자와 Google 뉴스
고급 검색 링크는 참고정보이며,
위험도·Telegram·PDF에 반영되지 않습니다.
Google 뉴스의 검색 기준과 참고정보 안내는 링크 옆 `?` 버튼에서 확인합니다.
ITS CCTV 목록과 영상 주소는 최대 1분 동안 캐시하며 영상 작업창의
`최신 영상 다시 요청`으로 즉시 재조회할 수 있습니다. ITS가
`filecreatetime`을 제공하면 영상 파일 생성 시각을 표시하고, 값이 없으면
촬영 시각을 추정하지 않고 영상 주소 조회 시각과 구분해 안내합니다.
ITS API에는 촬영 방위각이 없으므로 방향을 자동 추정하지 않습니다.
검증된 고정형 CCTV 방향만
[`safety_dashboard/config/cctv_directions.toml`](safety_dashboard/config/cctv_directions.toml)에
등록하면 지도 화살표와 CCTV 목록·영상 작업창에 표시됩니다. 초기 설정은
비어 있으며, 항목을 추가할 때는 `directions = []` 줄을 지우고 파일의
`[[directions]]` 예시 형식을 사용합니다. CCTV명과 위·경도가 소수점 5자리까지
모두 일치해야 적용되고, PTZ·가변 카메라는 등록하지 않습니다.

단일 시설 마커를 선택할 때는 지도 배율을 유지하고 해당 위치로만 이동합니다.
카카오 숫자 클러스터는 기존처럼 확대하고, 검색과 `facility_id` 딥링크는
화면 밖 시설을 찾는 동작이므로 이동과 확대를 함께 수행합니다. 전국 기온·바람
애니메이션과 예보는 타일 가공 파이프라인과 모바일 성능 검증이 필요해 보류합니다.

화면의 6개 시설 유형 그룹은
[`safety_dashboard/config/facility_groups.toml`](safety_dashboard/config/facility_groups.toml)에서
관리합니다. 어떤 그룹에도 등록되지 않은 시설 유형은 `기타시설`에 자동으로
포함됩니다.

지도와 시설 영향도는 기상청 특보구역 코드 및 공식 GeoJSON을 기준으로
계산합니다. 공식 경계는 하루 단위로 갱신하며 연결 실패 시 내장 스냅샷을
사용합니다.

## 검증

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m unittest discover -s tests_v3 -v
.venv/bin/python -m compileall -q app.py safety_dashboard
cd field_web && npm test && npm run build
```

운영 배포 전에는 코드 저장소 이력에 존재했던 기존 KMA 키를 재발급하여
`.streamlit/secrets.toml`의 값을 교체해야 합니다.
