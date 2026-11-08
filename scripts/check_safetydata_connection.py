"""Owner Cloud Shell: scoped runtime access and one official API read. No deployments."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request

PROJECT = "keco-safety-map"
SECRET = "SAFETY_DATA_API_KEY"
RUNTIME = "safety-dashboard-runtime@keco-safety-map.iam.gserviceaccount.com"
API_URL = "https://www.safetydata.go.kr/V2/api/DSSP-IF-00247"
KST = dt.timezone(dt.timedelta(hours=9))


class CheckFailed(Exception):
    pass


def gcloud(arguments):
    env = dict(os.environ)
    env.update(CLOUDSDK_CORE_LOG_HTTP="false", CLOUDSDK_CORE_VERBOSITY="error",
               CLOUDSDK_CORE_DISABLE_FILE_LOGGING="true", CLOUDSDK_CORE_LOG_FILE=os.devnull)
    try:
        result = subprocess.run(["gcloud", *arguments, "--project="+PROJECT, "--quiet"],
                                capture_output=True, text=True, timeout=40, env=env)
    except (OSError, subprocess.TimeoutExpired):
        raise CheckFailed("gcloud_unavailable") from None
    if result.returncode:
        code = "permission_denied" if "PERMISSION_DENIED" in result.stderr.upper() else "gcloud_failed"
        raise CheckFailed(code)
    return result.stdout


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def read_api(key, day, *, region="대구광역시", page=1, size=1):
    params = {"serviceKey": key, "pageNo": page, "numOfRows": size, "returnType": "json"}
    if day is not None:
        params["crtDt"] = day.strftime("%Y%m%d")
    if region:
        params["rgnNm"] = region
    query = urllib.parse.urlencode(params)
    # Never log this URL or a provider exception: either may contain the key.
    try:
        request = urllib.request.Request(API_URL+"?"+query, headers={"Accept": "application/json"})
        with urllib.request.build_opener(NoRedirect).open(request, timeout=15) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise CheckFailed("response_too_large")
        return json.loads(raw)
    except CheckFailed:
        raise
    except Exception:
        raise CheckFailed("official_api_read_failed") from None


def nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from nodes(child)


def summarize(payload):
    if not isinstance(payload, (dict, list)):
        raise CheckFailed("unexpected_response")
    mappings = list(nodes(payload))
    for item in mappings:
        if any(item.get(k) for k in ("returnAuthMsg", "errMsg", "errorMessage")) or item.get("resultCode") not in (None, "", "00", 0, "0"):
            raise CheckFailed("official_api_rejected_request")
    rows = [item for item in mappings if ("SN" in item or "sn" in item) and
            any(k in item for k in ("MSG_CN", "msgCn", "msg_cn"))]
    if not rows:
        empty = payload == [] or any(any(k in item and str(item[k]).strip() == "0"
                    for k in ("totalCount", "totalCnt", "TOTAL_COUNT", "total_count")) for item in mappings)
        if not empty:
            raise CheckFailed("message_fields_not_found")
        return {"api_result": "valid_empty_response", "sample_rows": 0}
    row = rows[0]
    fields = {"official_id": any(k in row for k in ("SN", "sn")),
              "text": any(k in row for k in ("MSG_CN", "msgCn", "msg_cn")),
              "issued_at": any(k in row for k in ("CRT_DT", "crtDt", "crt_dt")),
              "recipient_regions": any(k in row for k in ("RCPTN_RGN_NM", "rcptnRgnNm"))}
    if not all(fields.values()):
        raise CheckFailed("message_fields_incomplete")
    return {"api_result": "sample_received", "sample_rows": len(rows), "fields_present": fields}


def check(*, grant_runtime=False, run=gcloud, fetch=read_api, now=lambda: dt.datetime.now(KST)):
    report = {"project": PROJECT, "secret": SECRET, "runtime_access_granted": False,
              "api_calls": 0, "deployments": 0, "messages_sent": 0, "collection_started": False,
              "probe_origin": "owner_cloud_shell"}
    try:
        metadata = json.loads(run(["secrets", "versions", "describe", "latest", "--secret="+SECRET, "--format=json"]))
        version = metadata.get("name", "").rsplit("/", 1)[-1]
        if metadata.get("state") != "ENABLED" or not re.fullmatch(r"[1-9][0-9]*", version):
            raise CheckFailed("enabled_secret_version_required")
        report["version"] = version
        if grant_runtime:
            run(["secrets", "add-iam-policy-binding", SECRET, "--member=serviceAccount:"+RUNTIME,
                 "--role=roles/secretmanager.secretAccessor", "--condition=None", "--format=none"])
            report["runtime_access_granted"] = True
        key = run(["secrets", "versions", "access", version, "--secret="+SECRET]).strip()
        if not key or any(c.isspace() for c in key) or len(key) > 16000:
            raise CheckFailed("secret_value_invalid")
        report["api_calls"] = 1
        report.update(summarize(fetch(key, now().astimezone(KST).date())))
        report["status"] = "passed"
    except CheckFailed as error:
        report.update(status="blocked", reason=str(error))
    except Exception:
        # No exception message/trace, raw provider response or secret value is exported.
        report.update(status="blocked", reason="check_failed")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grant-runtime", action="store_true", help="Grant the runtime read access to this secret only")
    args = parser.parse_args(argv)
    report = check(grant_runtime=args.grant_runtime)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("확인 완료" if report["status"] == "passed" else "연결 확인 중단: 위 reason을 확인해 주세요.")
    print("키 값·문자 원문은 출력하지 않았습니다. 서버 배포·자동 수집·발송은 실행하지 않았습니다.")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
