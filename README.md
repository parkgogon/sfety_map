# 스마트 기상·재난 관제 대시보드

대구경북환경본부 소관시설 권역(대구·경북·부산·울산·경남)의 기상특보,
시설 영향도와 확인 우선순위를 조회하고, Telegram 요청과 PDF 보고서를 만드는
Streamlit 대시보드입니다.

## 실행

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .streamlit/secrets.example.toml .streamlit/secrets.toml
.venv/bin/streamlit run app_v3.py
```

`.streamlit/secrets.toml`에 KMA API 키와 텔레그램 설정을 입력해야 합니다.
실제 비밀정보 파일은 Git에서 제외됩니다.

## v3 주요 구조

```text
safety_dashboard/domain/       외부 기술에 독립적인 모델과 위험도 정책
safety_dashboard/application/  조회 snapshot과 Telegram 메시지 유스케이스
safety_dashboard/adapters/     KMA·CSV·특보구역·Telegram·PDF 연동
safety_dashboard/ui/           지도와 외부 CSS
safety_dashboard/config/       사람이 수정하는 위험도 기준표
app_v3.py                      얇은 Streamlit 화면 조립
tests_v3/                      v3 핵심 규칙 테스트
```

기존 `app.py`, `app_v2.py`와 기존 모듈은 비교와 복구를 위해 당분간 유지합니다.

제품 목표, 업무 규칙과 구조는 [`docs/`](docs/README.md)에 정리되어 있습니다.

기본 위험도 기준은
[`safety_dashboard/config/risk_policy.toml`](safety_dashboard/config/risk_policy.toml)에서
특보별 `ADVISORY`, `WARNING`, `CRITICAL` 값을 수정합니다. 값을 바꾸면 반드시
`policy.version`도 함께 올려 보고서가 어떤 기준을 사용했는지 식별할 수 있게 합니다.
화면의 `위험도 기준 설정`에서도 전체 특보 행렬을 편집할 수 있으며,
이 경우는 파일을 바꾸지 않고 현재 브라우저 세션에만 적용됩니다.

시설 유형·지도 표시 등급은 여러 개를 바꾼 뒤 `조회 범위 적용`을
눌러야 지도와 지표에 반영됩니다. 후속 작업 표의 체크 변경도
Telegram 또는 PDF 버튼을 누를 때 한 번에 확정됩니다.

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
.venv/bin/python -m compileall -q app_v3.py safety_dashboard
```

운영 배포 전에는 코드 저장소 이력에 존재했던 기존 KMA 키를 재발급하여
`.streamlit/secrets.toml`의 값을 교체해야 합니다.
