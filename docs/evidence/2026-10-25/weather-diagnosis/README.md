# 기상 실황 조회 실패 진단 — 2026-10-25 KST

**확인된 장애는 운영 API의 KMA 요청 연결 시간 초과다.** 시설별 기상 API에서 실제 `ConnectTimeout`을 확인했다.
격자 레이어도 약 7초 후 초기 좌표 조회 실패로 끝난다. 두 경로의 공통 연결 문제 가능성이 가장 높다.
어느 VPC/NAT/방화벽·원격 접근 정책이 원인인지까지 확정한 것은 아니다.

운영 앱 소스 `616d7a2`, 문서 기준 `55045ea`. 애플리케이션 코드·API 계약·운영 설정을 바꾸거나 재배포하지 않았다.
실제 발송·운영 dispatch·Worker 시험 경로도 호출하지 않았다. 환경 revision 24/current/enforced,
HTTPS 프록시·CA 신뢰·TLS 검증을 유지했다. 키·쿠키·query·외부 응답 원문은 저장하지 않았다.

## 확인된 사실

| 확인 위치/경로 | 실제 결과 | 해석 |
|---|---|---|
| 운영 `/api/v1/facilities/3077/weather` | HTTP 200, 상태 ERROR, `현재 기상 조회 실패: ConnectTimeout`, 7.342초 | 운영 API의 KMA 요청이 연결 단계에서 시간 초과 |
| 운영 `/api/v1/weather/layers/wind` | HTTP 200, ERROR/0점, `기상청 격자 위치를 확인하지 못했습니다.`, 7.523초 | 좌표 준비 단계 실패. 이 경로는 세부 예외 종류를 공개하지 않음 |
| 관리 환경 KMA 위도/경도 API | 각각 HTTP 200, 37,697값, 4.296/4.277초 | 제공된 관리 환경 자격증명·프록시 경로에서는 원본 좌표 정상 |
| 실제 좌표의 관제 권역 계산 | 1,244개 격자, 0.274초 | 좌표 순서·크기·권역 처리에서 실패를 재현하지 못함 |
| 같은 실제 좌표로 KMA 기온 조회 | LIVE·1,244점, 1.975초 | 관리 환경에서는 실제 기온 자료와 파서 정상 |
| 로컬 API 이미지 1 CPU/1GiB | 원래 provider의 좌표→기온 전체 조회 LIVE·1,244점, 8.502초 | 단위 테스트용 가짜 응답 없이 이미지/의존성/계산 경로 정상 |
| 운영의 새 지도 포함 PDF | HTTP 200·지도 captured, 7.925초 | 같은 서비스에서 소유 원점/Kakao로 나가는 HTTPS는 동작. 외부 통신 전체 장애로 보기 어려움 |

[원본/운영 비교](checks.json), [API 이미지 확인](container-check.json), [운영 HTTPS 대조](production-egress-control.json).
위도/경도 비교는 실제 응답을 재사용해 계산과 자료 조회를 분리했고, 이미지 확인은 원래 provider로 전체 원본 요청을 다시 실행했다.
**관리 환경·로컬 이미지 결과를 운영 Cloud Run 성공으로 표시하지 않는다.** 두 환경의 실제 키 값이 같다는 것도 확인하지 않았다.
PDF 대조의 Chromium과 Python requests는 HTTP 클라이언트가 달라, 모든 프록시/연결 설정이 같다는 보증은 아니다.

## 원인이 좁혀진 범위

- 지도 UI·Kakao 타일·PDF 고도화에서 시작된 오류가 아니다. 별도 시설 기상과 격자 기상이 같은 `apihub.kma.go.kr`에 요청한다.
  시설 기상은 `ConnectTimeout`, 격자는 초기 좌표 단계 오류이므로 표시보다 앞선 KMA 연결 경로를 먼저 봐야 한다.
- 시설별 provider의 기본 제한은 7초다. HTTP 인증/쿼터 응답을 받은 오류가 아니라 연결 시간 초과가 관찰됐다.
  일반적인 401/403·429나 응답 파싱 오류로 진단할 근거는 없다. 실제 운영 키의 서비스 권한 자체는 미확인이다.
- 격자 provider는 HTTP·연결·파싱 오류를 같은 문구로 감춘다. **격자 요청 자체의 예외가 `ConnectTimeout`이라고 직접 확인한 것은 아니다.**
  운영 지연 시간과 독립 시설 기상의 실제 예외가 공통 연결 문제 추정을 뒷받침한다.
- 특보는 LIVE로 보인다. [모니터링 메타데이터](monitoring-metadata.json)의 KMA 기준은 13:25:02 KST다.
  코드가 Firestore 공통 snapshot/캐시를 우선 사용하므로 이 표시는 API 서비스 자신의 현재 KMA 연결 성공을 증명하지 않는다.
  Worker 애플리케이션의 시험 호출이나 운영 강제 새로고침은 하지 않았다.
- 시간 제한만 늘리거나 키를 바꾸기 전에 API 서비스의 실제 출구·프록시·KMA 접근 경로를 확인하는 것이 우선이다.
  좌표를 고정 파일로 바꿔도 실황 값 조회 역시 같은 KMA 호스트를 사용하므로 연결 문제 전체가 해결되지는 않는다.

## 아직 확인하지 못한 설정과 다음 확인

현재 환경에는 연결된 GCP outbound identity/자격증명 manifest와 `gcloud`가 없다.
Cloud Run의 실제 VPC connector/direct VPC·egress·NAT/방화벽 설정과 runtime 로그를 읽을 수 없어
특정 규칙·출구 IP·IPv4/IPv6·KMA 측 차단 중 하나로 확정하지 않았다. 관리 환경 허용 도메인 추가가 필요한 상태로 단정하지 않는다.

Cloud Shell의 저장소 루트에서 다음 **읽기 전용** 수집 명령으로 API/Worker의 네트워크 설정 차이를 확인할 수 있다.

```bash
git pull --ff-only
python3 docs/evidence/2026-10-25/weather-diagnosis/collect_cloud_run_readonly.py
```

이 도구는 두 Cloud Run 서비스의 제어 영역 메타데이터만 조회한다. Worker 애플리케이션 URL에 접속/실행하지 않는다.
Secret 값·프록시 값은 출력하지 않으며 리비전·네트워크 annotation·프록시 변수의 존재·KMA Secret 참조만 출력한다.
현재 환경에서는 문법/`--help`와 가짜 제어 영역 응답으로 `describe` 명령 제한·비밀값 제외를 확인했다.
이 도구의 **GCP 실제 조회는 실행하지 않았다.**
annotation이 없다는 사실만으로 프로젝트의 상속 정책·NAT·방화벽이 정상이라고 결론 내리지 않는다.

비교 순서는 API/Worker의 실제 리비전과 네트워크 경로 → VPC 사용 시 route/NAT/egress firewall →
KMA 호스트까지의 연결/TLS 및 접근 허용 정책이다. 비밀값을 노출하거나 프록시/TLS를 우회하지 않는다.

진단 증빙 무결성: [SHA-256](SHA256SUMS). [현재 인계](../../../HANDOFF.md).
