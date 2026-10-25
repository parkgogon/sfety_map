# 기상 실황 조회 실패 진단 — 2026-10-25 KST

**운영 API의 KMA 연결 시간 초과는 18:33 KST에도 남는다.** 반면 같은 배포 이미지의 임시 Cloud Run Job은
18:19에는 연결 실패, 18:29에는 TCP·TLS와 홈페이지 HTTP 200이었다. 실행 인스턴스·출구·요청 시점 등의 차이를
더 구분해야 하며, Cloud Run 전체의 상시 차단이나 고정된 TLS 버전 오류로 단정할 수 없다.
운영 격자도 약 7초 후 초기 좌표 조회 실패로 끝난다. 정확한 원인은 아직 미확정이다.

운영 앱 소스 `616d7a2`, 문서 기준 `55045ea`. 애플리케이션 코드·API 계약·운영 설정을 바꾸거나 재배포하지 않았다.
실제 발송·운영 dispatch·Worker 시험 경로도 호출하지 않았다. 초기 환경 revision 24, 후속 31/current/enforced,
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
| 사용자 Cloud Shell의 KMA 홈페이지 | HTTP 200, IP `203.247.91.39`, TLS 완료 0.438초 | Cloud Shell 경로는 정상. 운영 API 경로와 다름 |
| 같은 배포 이미지의 서울 Cloud Run Job | 홈페이지·격자 좌표·시설 격자 모두 `ConnectTimeout`, 7.012/7.027/7.020초 | 키/앱을 쓰지 않는 별도 Cloud Run 실행에서도 연결 실패를 재현 |
| 두 번째 서울 Cloud Run Job | API Hub TCP 58ms·TLS 7ms·HTTP 200/131ms, 날씨누리 HTTP 200/70ms | 해당 실행에서는 정상 연결. 인증 API·운영 인스턴스의 성공은 아님 |
| 두 번째 Job 후 운영 직접 재확인 | 시설 `ConnectTimeout`/7.555초, 바람 ERROR·0점/7.715초 | 별도 Job 성공과 운영 API의 회복을 구분 |

[원본/운영 비교](checks.json), [API 이미지 확인](container-check.json), [운영 HTTPS 대조](production-egress-control.json).
[사용자 제공 Cloud Run 실제 진단·삭제 결과](cloud-run-keyless-result.json)는 18:19 KST 실행이다.
[두 번째 Job의 단계 계측·삭제 결과](cloud-run-stages-result.json)는 18:29 KST,
[그 이후 운영 API 재확인](production-after-stage-success.json)은 18:33 KST다.
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

현재 관리 환경에는 연결된 GCP outbound identity/자격증명 manifest와 `gcloud`가 없다.
사용자가 Cloud Shell에서 아래 도구를 실행한 결과를 제공했다. API/Worker 조회 모두 성공했고, 최신 ready revision은
각각 `safety-dashboard-api-00086-zn7` / `safety-alert-worker-00074-47k`였다.
두 서비스 모두 같은 runtime 서비스 계정과 `KMA_API_KEY:1`을 사용하며, 검사한 VPC connector/direct VPC·egress annotation은
모두 null, 프록시 환경 변수 이름은 없었다. **조회한 항목에서 두 서비스의 네트워크 설정 차이는 발견되지 않았다.**
프로젝트 전체 경로·상속 정책·실제 출구 IP·runtime 로그를 확인한 것은 아니므로 특정 NAT/방화벽·KMA 측 차단으로 확정하지 않는다.
관리 환경 허용 도메인 추가가 필요한 상태로 단정하지 않는다.

후속 공개 운영 재확인에서도 시설 기상은 `ConnectTimeout`/7.510초였다. 동시에 특보는 17:55:01 KST 기준 LIVE였다.
관리 환경에서 격자 좌표·시설 격자·특보 주소를 각각 리디렉션 없이 조회하면 모두 HTTP 200이었고 Location 헤더가 없었다.
따라서 이번 관리 환경 요청에서는 다른 호스트/프로토콜로의 리디렉션을 관찰하지 못했다. 운영 요청의 redirect history는 미확인이다.

Cloud Shell의 저장소 루트에서 다음 **읽기 전용** 수집 명령으로 API/Worker의 네트워크 설정 차이를 확인할 수 있다.

```bash
git pull --ff-only
python3 docs/evidence/2026-10-25/weather-diagnosis/collect_cloud_run_readonly.py
```

이 도구는 두 Cloud Run 서비스의 제어 영역 메타데이터만 조회한다. Worker 애플리케이션 URL에 접속/실행하지 않는다.
Secret 값·프록시 값은 출력하지 않으며 리비전·네트워크 annotation·프록시 변수의 존재·KMA Secret 참조만 출력한다.
관리 환경에서는 문법/`--help`와 가짜 제어 영역 응답으로 `describe` 명령 제한·비밀값 제외를 확인했다.
**GCP 실제 조회는 사용자의 Cloud Shell에서 실행됐고, 관리 환경에서 직접 실행한 것은 아니다.**
annotation이 없다는 사실만으로 프로젝트의 상속 정책·NAT·방화벽이 정상이라고 결론 내리지 않는다.

사용자 Cloud Shell에서 인증키 없는 KMA 홈페이지 연결을 확인했다. 결과는 HTTP 200,
원격 IP `203.247.91.39`, 연결 0.382302초·TLS 완료 0.438218초·전체 2.355972초였다.
이는 **Cloud Shell 경로의 연결 성공**이며, 운영 Cloud Run 인스턴스의 통신 성공은 아니다.
KMA 전체 장애나 모든 Google Cloud 출구 차단으로 해석할 근거는 줄었지만, 운영의 정확한 실패 원인은 미확정이다.

이어 사용자 Cloud Shell에서 최초 임시 Cloud Run Job의 실행을 완료했다. 실제 운영 트래픽 100%인 API revision의
이미지 digest를 사용했고, keyless 홈페이지와 격자 두 주소 모두 약 7초 후 `ConnectTimeout`이었다.
DNS 결과는 Cloud Shell과 같은 `203.247.91.39`였다. 실행 명령 성공은 **진단 프로그램 완료**를 뜻하며 통신 성공이 아니다.
임시 Job 삭제 명령 성공도 확인했다. 운영 API·Worker·발송 기능은 호출/변경하지 않았다.

첫 Job은 키 없는 홈페이지도 실패했다. 두 번째 Job은 같은 이미지·리전·목적지 IP에서 TCP/TLS/HTTP 모두 성공했고 삭제도 완료했다.
두 번째 Job은 인증된 실황을 조회하지 않았으며, 실패했던 첫 Job의 TCP/TLS 세부 단계도 알 수 없다.
18:33 KST 운영 시설 기상·바람 격자는 여전히 실패했으므로 운영 복구로 표시하지 않는다.
API 프로세스 자신의 DNS/출구 IP, 두 Job의 실제 출구 IP, 운영 key의 현재 서비스 권한/리디렉션은 아직 미확인이다.
연결 실패의 존재와 현재 운영 실패의 단일 원인을 혼동하지 않는다.

## 다음 확인: 같은 Secret 참조와 원래 provider의 인증된 실황 비교

Cloud Shell의 curl과 운영 Python requests는 실행 위치와 TLS 클라이언트가 다르다.
이를 좁히기 위해 [임시 진단 도구](run_temporary_kma_probe.py)를 보완했다.
기본 실행은 운영 트래픽 100%인 API revision과 immutable 이미지 digest를 읽고 계획만 출력한다.
`--execute`를 주면 **임시 Cloud Run Job을 새로 생성·1회 실행·로그 수집·삭제**한다. 읽기 전용 동작과 구분한다.
`--with-kma-key`를 추가하면 활성 API revision이 참조한 **고정 KMA Secret 버전 하나만** Job에 연결한다.
키 값은 Cloud Shell/도구/출력으로 꺼내지 않고 Job의 KMA 요청에서만 사용한다. 관리자/Telegram/SMS Secret은 연결하지 않는다.
운영 API·Worker·Scheduler 설정과 트래픽은 변경하지 않으며, 기존 애플리케이션/발송 경로를 호출하지 않는다.

- 같은 API 이미지·서울 리전·runtime 서비스 계정, 1 CPU/1GiB, 1 task·재시도 0이다.
  기본 keyless 검사는 최대 90초, 인증된 provider 검사는 최대 180초다. Python 명령을 덮어써 서버를 시작하지 않는다.
  기본 모드는 Secret/운영 환경 변수/시설 자료를 읽거나 연결하지 않는다.
- DNS 주소, Python/OpenSSL/requests 버전과 KMA API 홈페이지·기상청 날씨누리의 HTTP 응답 또는 예외 종류·소요 시간을 출력한다.
  기존 requests가 호출하는 TCP 연결과 TLS socket wrapping을 그대로 감싸 단계별 성공·예외 종류·시간을 기록한다.
  직접 socket 연결이나 TLS 버전·cipher·timeout 설정 변경은 하지 않는다. 원래 API revision의 실행 세대 annotation도 읽는다.
  인증키를 사용하지 않으므로 401/403 등의 HTTP 응답도 연결 성립 증거이며, 기상 자료/API 권한 검증은 아니다.
  응답 본문·프록시 값·예외 원문은 출력하지 않고 기본 프록시/CA/TLS 검증을 유지한다.
- 인증 모드는 이미지 안의 원래 `GridWeatherLayerProvider`로 기온을 조회하고, CSV에서 실제 시설 ID `3077`의 위치를 읽어
  원래 `CurrentWeatherProvider`로 시설 기상을 조회한다. 원본 응답은 메모리에서 파싱하며 상태·점 수·호스트/경로·HTTP/TCP/TLS 메타데이터만 출력한다.
  진단용 전송 래퍼는 실제 requests 응답을 반환하며 가짜 API를 사용하지 않는다. 단, **첫 HTTP 응답을 보기 위해 리디렉션은 따르지 않는다.**
  리디렉션은 목적지 호스트만 기록하고 query는 출력하지 않는다. 따라서 리디렉션이 있으면 운영 기본 동작과 차이를 별도로 해석한다.
  Firestore·보고서 저장·앱 서버·Worker·발송 기능은 사용하지 않는다.
- API의 실제 revision에 명시적 VPC·프록시가 있거나 트래픽이 분할되어 있으면 일치 여부를 추측하지 않고 생성 전에 중단한다.
  실행 중 오류에도 해당 임시 Job만 삭제를 시도하고 성공 여부를 출력한다. false이면 출력된 `kma-net-diag-*` Job만 정리한다.
- Job은 운영 중인 API 인스턴스와 **출구 IP·실행 세대·CPU 할당 방식이 같다는 보증이 없다.**
  Job 성공을 운영 복구로 표시하지 않는다. 결과가 비어 있거나 실행이 실패하면 미검증으로 남긴다.

사용자의 기존 Cloud Shell 저장소에서 실행할 명령:

```bash
git -C ~/sfety_map-diagnosis pull --ff-only &&
python3 ~/sfety_map-diagnosis/docs/evidence/2026-10-25/weather-diagnosis/run_temporary_kma_probe.py --execute --with-kma-key
```

현재 관리 환경에는 GCP identity/gcloud가 없어 직접 제어 영역 조회/Job 실행은 할 수 없다.
**keyless Job 두 번은 사용자가 실제 실행·삭제했다. 인증된 provider의 Cloud Run 검사는 아직 실행하지 않았다.**
가짜 gcloud/HTTP 응답을 사용하는 도구 테스트 13개를 공통 외부 통신 차단 실행기로 확인했다(실제 HTTP/TCP 0건).
TCP/TLS 구분·복원, 고정 Secret 하나만 연결·누락 시 생성 전 중단, 키/본문/리디렉션 query 제외를 확인했다.
또한 [로컬 개발 이미지의 실제 계측 확인](local-stage-instrumentation.json)에서 두 호스트 모두 HTTP 200과 TCP/TLS 단계 기록을 확인했다.
이는 관리 프록시·신뢰 CA를 통한 계측 동작 확인이며, 직접 KMA TLS나 운영 Cloud Run 성공이 아니다.
인증 모드도 [로컬 개발 이미지에서 실제 원본 조회](local-authenticated-provider.json)했다. 기온 LIVE·1,244점과 시설 기상 LIVE였다.
관리 환경의 제공된 KMA 자격증명·프록시 경로로 검증했으며, 운영 Secret 값/권한이 같다는 보증이나 운영 성공은 아니다.
문법/`--help`를 확인했고 기존에 통과한 제품 테스트·브라우저 검수는 반복하지 않았다.
CLI 명령·인자 전달·로그 필터는 [Job 생성](https://cloud.google.com/sdk/gcloud/reference/run/jobs/create),
[인자 구분자](https://cloud.google.com/sdk/gcloud/reference/topic/escaping),
[Cloud Run 로그](https://cloud.google.com/run/docs/logging) 공식 문서와 대조했다.

인증된 provider도 LIVE이면 같은 이미지·Secret 참조·원래 처리 로직이 별도 Cloud Run 실행에서 동작한 것으로 보고
운영 인스턴스의 경로·실행 조건 차이를 우선 비교한다. 인증/리디렉션/파싱 오류가 관찰되면 그 실제 HTTP 증거로 범위를 좁힌다.
어느 결과도 단독으로 특정 주체의 IP 차단이나 운영 복구를 확정하지 않는다. 현재 근거로 TLS를 낮추거나 유료 고정 출구를 도입하지 않는다.

진단 증빙 무결성: [SHA-256](SHA256SUMS). [현재 인계](../../../HANDOFF.md).
