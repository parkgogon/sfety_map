# 스마트 기상·재난 관제 대시보드

대구경북환경본부 소관시설 권역(대구·경북·부산·울산·경남)의 기상특보,
시설 영향도, 현장 점검 우선순위와
PDF 보고서를 제공하는 Streamlit 대시보드입니다.

## 실행

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .streamlit/secrets.example.toml .streamlit/secrets.toml
.venv/bin/streamlit run app_v2.py
```

`.streamlit/secrets.toml`에 KMA API 키와 텔레그램 설정을 입력해야 합니다.
실제 비밀정보 파일은 Git에서 제외됩니다.

## 주요 구조

```text
app_v2.py                  v2 화면과 사용자 흐름
core/region_resolver.py    특보구역·시설주소·지도경계 매칭
data/                      기상청 공식 특보구역 장애 대비 스냅샷
services/                  데이터 검증과 메시지 조합
ui/                        화면 컴포넌트, 테마, Folium 지도
data_providers/            KMA 등 외부 데이터 제공자
risk_engine.py             시설 위험도 산정
report_generator.py        HTML/PDF 보고서
tests/                     핵심 규칙 회귀 테스트
```

기존 `app.py`는 비교와 복구를 위한 레거시 화면으로 유지합니다.

지도와 시설 영향도는 기상청 특보구역 코드 및 공식 GeoJSON을 기준으로
계산합니다. 공식 경계는 하루 단위로 갱신하며 연결 실패 시 내장 스냅샷을
사용합니다.

## 검증

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q app_v2.py core services ui
```

운영 배포 전에는 코드 저장소 이력에 존재했던 기존 KMA 키를 재발급하여
`.streamlit/secrets.toml`의 값을 교체해야 합니다.
