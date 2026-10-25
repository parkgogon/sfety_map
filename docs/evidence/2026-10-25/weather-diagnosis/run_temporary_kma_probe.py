"""운영 API 이미지의 임시 Cloud Run Job으로 KMA 연결만 검사한다.

기본 실행은 제어 영역 조회/계획 출력뿐이다. --execute는 임시 Job을 생성·1회 실행·삭제한다.
운영 서비스/Worker/Scheduler를 변경하거나 호출하지 않고 Secret을 연결하지 않는다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import time
import uuid

PREFIX = "KMA_NET_DIAG "
PAYLOAD = r'''
import datetime, json, os, platform, socket, ssl, time
import requests
import urllib3.util.connection

result = {
    "scope": "Temporary Cloud Run Job, not the running production API instance. No key, app or Worker calls.",
    "checkedAtUTC": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "python": platform.python_version(), "openssl": ssl.OPENSSL_VERSION,
    "requests": requests.__version__, "tlsVerification": True,
    "proxyVariableNamesPresent": sorted(k for k in os.environ if k.lower() in
        {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}),
    "checks": [],
}
try:
    result["resolvedIPs"] = sorted({item[4][0] for item in socket.getaddrinfo(
        "apihub.kma.go.kr", 443, type=socket.SOCK_STREAM)})
except OSError as error:
    result["dnsErrorType"] = type(error).__name__
original_connect = urllib3.util.connection.create_connection
original_wrap = ssl.SSLContext.wrap_socket
steps = []

def measured(stage, function, *args, **kwargs):
    start = time.monotonic()
    entry = {"stage": stage}
    try:
        value = function(*args, **kwargs)
        entry["succeeded"] = True
        return value
    except Exception as error:
        entry.update(succeeded=False, errorType=type(error).__name__)
        raise
    finally:
        entry["elapsedMs"] = round((time.monotonic() - start) * 1000)
        steps.append(entry)

def traced_connect(*args, **kwargs):
    return measured("tcp_connect", original_connect, *args, **kwargs)

def traced_wrap(*args, **kwargs):
    return measured("tls_wrap", original_wrap, *args, **kwargs)

# 계측은 기존 호출을 그대로 감싼다. 직접 socket 연결·프록시 우회·TLS 설정 변경은 없다.
urllib3.util.connection.create_connection = traced_connect
ssl.SSLContext.wrap_socket = traced_wrap
try:
  for host, path in [("apihub.kma.go.kr", "/"),
                     ("www.weather.go.kr", "/w/special-report/overall.do")]:
    steps = []
    record = {"host": host, "path": path, "authenticated": False, "stages": steps}
    start = time.monotonic()
    try:
        # requests의 기본 프록시/CA/TLS 검증 유지. 본문/query/비밀값을 출력하지 않는다.
        with requests.get("https://" + host + path, timeout=(7, 7),
                          allow_redirects=False, stream=True) as response:
            record["httpStatus"] = response.status_code
            record["headersReceived"] = True
            record["redirectPresent"] = bool(response.headers.get("Location"))
    except requests.RequestException as error:
        record["errorType"] = type(error).__name__
    record["elapsedMs"] = round((time.monotonic() - start) * 1000)
    result["checks"].append(record)
finally:
    urllib3.util.connection.create_connection = original_connect
    ssl.SSLContext.wrap_socket = original_wrap
print("KMA_NET_DIAG " + json.dumps(result, ensure_ascii=False), flush=True)
'''


def command(arguments, *, check=True, timeout=60):
    process = subprocess.run(["gcloud", *arguments], capture_output=True,
                             text=True, timeout=timeout)
    if check and process.returncode:
        # describe 응답/환경 전체와 gcloud 원문 stderr는 출력하지 않는다.
        raise RuntimeError(f"gcloud {arguments[0]} {arguments[1]} failed: exit {process.returncode}")
    return process


def read_json(arguments):
    return json.loads(command([*arguments, "--format=json"]).stdout)


def production_image(project, region):
    scope = ["--project", project, "--region", region]
    service = read_json(["run", "services", "describe", "safety-dashboard-api", *scope])
    status = service.get("status", {})
    traffic = [item for item in status.get("traffic", []) if item.get("percent", 0)]
    if len(traffic) != 1 or traffic[0].get("percent") != 100:
        raise RuntimeError("API traffic is split or unknown; no Job created.")
    revision = traffic[0].get("revisionName")
    if not revision and traffic[0].get("latestRevision"):
        revision = status.get("latestReadyRevisionName")
    if not revision or not revision.startswith("safety-dashboard-api-"):
        raise RuntimeError("Actual API revision is unknown; no Job created.")
    detail = read_json(["run", "revisions", "describe", revision, *scope])
    annotations = detail.get("metadata", {}).get("annotations", {})
    network_keys = ("run.googleapis.com/vpc-access-connector",
                    "run.googleapis.com/vpc-access-egress",
                    "run.googleapis.com/network-interfaces")
    if any(annotations.get(key) for key in network_keys):
        raise RuntimeError("API has explicit VPC settings; review matching Job network first.")
    spec = detail.get("spec", {})
    containers = spec.get("containers", [])
    if len(containers) != 1:
        raise RuntimeError("API container layout is unsupported; no Job created.")
    if any(item.get("name", "").lower() in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}
           for item in containers[0].get("env", [])):
        raise RuntimeError("API has explicit proxy settings; review matching Job proxy first.")
    image = containers[0].get("image", "")
    digest = detail.get("status", {}).get("imageDigest", "")
    if "@sha256:" in digest:
        image = digest
    elif digest.startswith("sha256:"):
        image = image.split("@", 1)[0].rsplit(":", 1)[0] + "@" + digest
    if "@sha256:" not in image or not spec.get("serviceAccountName"):
        raise RuntimeError("Immutable API image or service account is unknown; no Job created.")
    return {"revision": revision, "image": image, "serviceAccount": spec["serviceAccountName"],
            "executionEnvironmentAnnotation": annotations.get("run.googleapis.com/execution-environment")}


def run_probe(project, region, source, *, pause=time.sleep):
    name = "kma-net-diag-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]
    scope = ["--project", project, "--region", region]
    created = False
    try:
        # --args custom delimiter keeps the complete Python source a single argument.
        created = True  # Cleanup also covers a create timeout with an unknown outcome.
        command(["run", "jobs", "create", name, *scope, "--quiet",
                 "--image", source["image"], "--service-account", source["serviceAccount"],
                 "--command", "python", "--args=^@^-c@" + PAYLOAD,
                 "--cpu", "1", "--memory", "1Gi", "--tasks", "1", "--parallelism", "1",
                 "--max-retries", "0", "--task-timeout", "90s"], timeout=180)
        execution = command(["run", "jobs", "execute", name, *scope,
                             "--wait", "--format=json", "--quiet"], check=False, timeout=240)
        data = read_json(["run", "jobs", "describe", name, *scope])
        execution_name = data.get("status", {}).get("latestCreatedExecution", {}).get("name")
        if not execution_name:
            raise RuntimeError("Diagnostic execution name is unavailable.")
        execution_name = execution_name.rsplit("/", 1)[-1]
        expression = (f'resource.type="cloud_run_job" AND resource.labels.job_name="{name}" '
                      f'AND resource.labels.location="{region}" '
                      'AND textPayload:"KMA_NET_DIAG "')
        records = []
        for attempt in range(6):
            entries = read_json(["logging", "read", expression, "--project", project,
                                 "--freshness=30m", "--limit=10"])
            for entry in entries:
                text = entry.get("textPayload", "")
                if text.startswith(PREFIX):
                    records.append(json.loads(text[len(PREFIX):]))
            if records:
                break
            if attempt < 5:
                pause(3)
        return {"job": name, "execution": execution_name,
                "executionCommandSucceeded": execution.returncode == 0,
                "productionSource": source, "probeResults": records,
                "note": "No result means unverified, not successful. Logs may arrive late."}
    finally:
        if created:
            deleted = False
            try:
                cleanup = command(["run", "jobs", "delete", name, *scope, "--quiet"],
                                  check=False, timeout=90)
                deleted = cleanup.returncode == 0
            except (subprocess.TimeoutExpired, OSError):
                pass
            print(json.dumps({"temporaryJob": name, "deleteCommandSucceeded": deleted,
                              "cleanupNote": "If false, inspect/delete only this diagnostic Job; no production resource was changed."},
                             ensure_ascii=False), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="keco-safety-map")
    parser.add_argument("--region", default="asia-northeast3")
    parser.add_argument("--execute", action="store_true", help="임시 Job을 생성·1회 실행하고 삭제한다")
    args = parser.parse_args(argv)
    if not shutil.which("gcloud"):
        parser.error("Cloud Shell 등 gcloud 계정이 있는 환경에서 실행하세요.")
    source = production_image(args.project, args.region)
    if not args.execute:
        print(json.dumps({"mode": "read-only plan", "productionSource": source,
                          "withExecute": "Create one temporary Job, run keyless KMA checks, collect its logs, delete it. No production updates or Worker calls."},
                         ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(run_probe(args.project, args.region, source), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.TimeoutExpired, ValueError) as error:
        print(json.dumps({"diagnosisCompleted": False, "errorType": type(error).__name__,
                          "detail": str(error) if isinstance(error, RuntimeError) else "Metadata/command failure; no secret values printed."},
                         ensure_ascii=False))
        raise SystemExit(1)
