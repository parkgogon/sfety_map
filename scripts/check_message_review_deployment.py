"""Read-only GCP metadata audit. Never reads secret payloads or Firestore documents."""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = "gpt-5.4-mini-2026-03-17"
KEYS = ("OPENAI_API_KEY", "KAKAO_REST_API_KEY", "SAFETY_DATA_API_KEY")
PROJECT = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]")
SECRET = re.compile(r"[A-Za-z0-9_-]{1,255}")
VERSION = re.compile(r"(?:latest|[1-9][0-9]*)")
DELIVERY_FLAGS = ("MESSAGE_NOTIFICATION_PREPARATION_ENABLED", "MESSAGE_COLLECTION_FAST_ENABLED",
                  "MESSAGE_AI_SPEND_BUDGET_ENABLED", "MESSAGE_EMERGENCY_FALLBACK_ENABLED", "MESSAGE_DELIVERY_ENABLED")


def delivery_metadata(project, *, query=None):
    """Existing services/schedules only. No payload access or permission changes."""
    query = query or gcloud_json
    if not PROJECT.fullmatch(project):
        raise ValueError("유효한 GCP 프로젝트 ID가 필요합니다.")
    report = {"services": {}, "schedules": {}, "telegram_references": [], "findings": []}
    for name in ("safety-dashboard-api", "safety-message-worker", "safety-alert-worker"):
        service, error = query(["run", "services", "describe", name, "--region", "asia-northeast3", "--project", project])
        spec = (service or {}).get("spec", {}).get("template", {}).get("spec", {})
        container = (spec.get("containers") or [{}])[0]
        env = {e.get("name"): e for e in container.get("env", [])}
        source = env.get("APP_REVISION", {}).get("value", "")
        flags = {k: env.get(k, {}).get("value", "false") == "true" for k in DELIVERY_FLAGS}
        report["services"][name] = {"metadata_status": error or "observed",
            "source_revision": source if re.fullmatch(r"[a-f0-9]{40}", source) else None,
            "delivery_flags": flags if not error else None}
        if error:
            report["findings"].append(name+"_metadata_"+error)
        # Read names/versions from the existing KMA binding, never plaintext chat IDs.
        if name == "safety-alert-worker" and not error:
            for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_USER_CHAT_ID", "TELEGRAM_CHAT_ID", "TELEGRAM_ADMIN_CHAT_ID"):
                if key not in env:
                    continue
                ref = env[key].get("valueFrom", {}).get("secretKeyRef", {})
                secret, version = ref.get("name", ""), ref.get("key", "")
                supported = bool(SECRET.fullmatch(secret) and VERSION.fullmatch(version))
                report["telegram_references"].append({"environment_key": key,
                    "secret_name": secret if supported else None, "version_reference": version if supported else None,
                    "numeric_version_pinned": bool(supported and version.isdigit())})
    for name in ("safety-message-collect", "safety-message-analyze", "safety-alert-dispatch"):
        job, error = query(["scheduler", "jobs", "describe", name, "--location", "asia-northeast3", "--project", project])
        job = job or {}
        schedule = job.get("schedule", "")
        report["schedules"][name] = {"metadata_status": error or "observed",
            "state": job.get("state") if job.get("state") in {"ENABLED", "PAUSED", "DISABLED"} else "unverified",
            "schedule": schedule if re.fullmatch(r"[0-9*/ ,\-]{9,80}", schedule) else None}
        if error:
            report["findings"].append(name+"_metadata_"+error)
    report["telegram_access"] = "not_tested_no_messages_sent"
    report["numeric_versions_require_confirmation"] = (not report["telegram_references"] or
        any(not row["numeric_version_pinned"] for row in report["telegram_references"]))
    return report


def gcloud_json(arguments):
    """Fixed metadata commands only; raw stdout/stderr never become a report."""
    try:
        result = subprocess.run(["gcloud", *arguments, "--format=json", "--quiet"],
            capture_output=True, text=True, timeout=25, check=False)
        if result.returncode:
            error = result.stderr.upper()
            code = "not_found" if "NOT_FOUND" in error else "permission_denied" if "PERMISSION_DENIED" in error else "unavailable"
            return None, code
        value = json.loads(result.stdout)
        return (value, "") if isinstance(value, dict) else (None, "invalid_metadata")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None, "unavailable"


def role_hint(policy, member, roles):
    if policy is None or not member:
        return "unverified"
    found = any(member in binding.get("members", []) and binding.get("role") in roles and not binding.get("condition")
                for binding in policy.get("bindings", []))
    # An allow entry does not evaluate deny policies, groups, custom roles, or runtime access.
    return "allow_binding_found" if found else "unverified"


def audit(project, *, query=gcloud_json, checked_at=None):
    if not PROJECT.fullmatch(project):
        raise ValueError("유효한 GCP 프로젝트 ID가 필요합니다.")
    common = ["--project", project]
    service_args = ["run", "services", "describe", "safety-dashboard-api", "--region", "asia-northeast3", *common]
    database_args = ["firestore", "databases", "describe", "--database", "(default)", *common]
    policy_args = ["projects", "get-iam-policy", project]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(query, args) for args in (service_args, database_args, policy_args)]
        (service, service_error), (database, database_error), (project_policy, project_policy_error) = [f.result() for f in futures]
    service = service or {}
    template = service.get("spec", {}).get("template", {})
    spec = template.get("spec", {})
    runtime = spec.get("serviceAccountName", "")
    member = "serviceAccount:" + runtime if re.fullmatch(r"[A-Za-z0-9_.-]+@[A-Za-z0-9.-]+\.gserviceaccount\.com", runtime) else ""
    containers = spec.get("containers", [])
    env = {item.get("name"): item for item in (containers[0].get("env", []) if containers else [])}
    findings = []
    if service_error: findings.append("cloud_run_metadata_" + service_error)
    if database_error: findings.append("firestore_metadata_" + database_error)
    if project_policy_error: findings.append("project_iam_metadata_" + project_policy_error)
    if database and database.get("type") != "FIRESTORE_NATIVE": findings.append("firestore_native_database_required")
    store = env.get("MESSAGE_REVIEW_STORE", {}).get("value", "firestore")
    if store != "firestore": findings.append("persistent_message_store_required")
    # Read only these fixed, non-secret values; never copy arbitrary environment values.
    configuration = {
        "message_store_firestore": store == "firestore" if not service_error else None,
        "model_matches_evaluated": env.get("OPENAI_MODEL", {}).get("value", MODEL) == MODEL if not service_error else None,
        "reasoning_low": env.get("OPENAI_REASONING_EFFORT", {}).get("value", "low") == "low" if not service_error else None,
        "admin_auth_configured": any(key in env for key in ("ADMIN_ACCESS_PASSWORD",)) if not service_error else None,
        "project_configured": any(env.get(key, {}).get("value") == project for key in ("GOOGLE_CLOUD_PROJECT", "GCP_PROJECT_ID")) if not service_error else None,
    }
    if not service_error:
        if not configuration["admin_auth_configured"]: findings.append("admin_auth_missing")
        if not configuration["project_configured"]: findings.append("runtime_project_missing")
        if not configuration["model_matches_evaluated"]: findings.append("model_differs_from_evaluation")
        if not configuration["reasoning_low"]: findings.append("reasoning_differs_from_evaluation")

    def inspect_secret(key):
        entry = env.get(key, {})
        ref = entry.get("valueFrom", {}).get("secretKeyRef", {})
        name, version = ref.get("name", key), ref.get("key", "latest")
        binding = "secret_reference" if ref else "plaintext_present" if entry.get("value") else "missing"
        if service_error: binding = "unverified"
        row = {"environment_key": key, "binding": binding, "required_for": "official_feed" if key == "SAFETY_DATA_API_KEY" else "manual_ai_review",
               "version_state": "unverified", "iam_hint": "unverified"}
        if not SECRET.fullmatch(name) or not VERSION.fullmatch(version):
            row["metadata_status"] = "external_or_unsupported_reference"
            return row
        meta, error = query(["secrets", "versions", "describe", version, "--secret", name, *common])
        policy, policy_error = query(["secrets", "get-iam-policy", name, *common])
        row["metadata_status"] = error or "observed"
        row["iam_metadata_status"] = policy_error or "observed"
        row["version_state"] = meta.get("state") if meta and meta.get("state") in ("ENABLED", "DISABLED", "DESTROYED") else "unverified"
        row["iam_hint"] = role_hint(policy, member, {"roles/secretmanager.secretAccessor", "roles/secretmanager.admin"})
        project_hint = role_hint(project_policy, member, {"roles/secretmanager.secretAccessor", "roles/secretmanager.admin"})
        if project_hint == "allow_binding_found": row["iam_hint"] = project_hint
        return row

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        secrets = list(pool.map(inspect_secret, KEYS))
    for row in secrets:
        if row["binding"] != "secret_reference": findings.append(row["environment_key"] + "_binding_" + row["binding"])
        if row["version_state"] != "ENABLED": findings.append(row["environment_key"] + "_version_unverified")
        if row["iam_hint"] == "unverified": findings.append(row["environment_key"] + "_iam_unverified")
    ready = any(c.get("type") == "Ready" and c.get("status") == "True" for c in service.get("status", {}).get("conditions", []))
    if not service_error and not ready: findings.append("cloud_run_not_ready")
    source = env.get("APP_REVISION", {}).get("value", "")
    return {"checked_at": checked_at or dt.datetime.now(dt.timezone.utc).isoformat(), "project": project,
        "audit_complete": not service_error and not database_error and project_policy is not None
            and all(s.get("metadata_status") in {"observed", "not_found"} and s.get("iam_metadata_status") in {"observed", "not_found"} for s in secrets),
        "service": {"metadata_status": service_error or "observed", "ready": ready if not service_error else None,
                    "source_revision": source if re.fullmatch(r"[a-f0-9]{7,40}", source) else None},
        "configuration": configuration,
        "firestore": {"metadata_status": database_error or "observed", "native": database.get("type") == "FIRESTORE_NATIVE" if database else None,
            "iam_hint": role_hint(project_policy, member, {"roles/datastore.user", "roles/datastore.owner", "roles/editor", "roles/owner"}),
            "runtime_read_write": "not_tested"},
        "secrets": secrets, "findings": findings,
        "unverified": ["runtime_secret_access", "firestore_transaction_and_history", "official_api_response_and_terms",
                       "real_kakao_sdk_on_message_screen", "mobile_device"],
        "boundaries": {"secret_payloads_read": 0, "firestore_documents_read_or_written": 0,
                       "model_place_feed_calls": 0, "deployments_or_messages_sent": 0}}


def markdown(report):
    lines = ["# 재난문자 운영 연결 메타데이터 점검", "", f"확인 시각: {report['checked_at']}",
        f"메타데이터 조회: {'완료' if report['audit_complete'] else '일부 미확인'}", "",
        "이 보고서는 설정 존재만 확인합니다. 실제 키 사용·저장 성공·지도 동작 검증을 대신하지 않습니다.", "",
        "| 서버 환경변수 | 연결 방식 | Secret 버전 | 권한 단서 |", "| --- | --- | --- | --- |"]
    for row in report["secrets"]:
        lines.append(f"| {row['environment_key']} | {row['binding']} | {row['version_state']} | {row['iam_hint']} |")
    if report.get("delivery_preflight"):
        data = report["delivery_preflight"]
        lines += ["", "## 자동전파 전환 준비", "", "기존 worker·예약·Telegram 참조만 읽었습니다. 운영방 접근·수신은 시험하지 않았습니다.",
                  "", "| 기존 KMA 환경변수 | Secret 이름 | 현재 버전 참조 |", "| --- | --- | --- |"]
        lines += [f"| {row['environment_key']} | {row['secret_name']} | {row['version_reference']} |" for row in data["telegram_references"]]
        if data["numeric_versions_require_confirmation"]:
            lines += ["", "고정 숫자 버전을 확인하기 전에는 자동전파 활성화 설정을 완성할 수 없습니다. latest를 1로 가정하지 않습니다."]
    lines += ["", "## 확인할 설정", ""] + [f"- `{finding}`" for finding in report["findings"]]
    if not report["findings"]: lines.append("메타데이터에서 연결 누락을 찾지 못했습니다. 실제 동작은 별도 검증해야 합니다.")
    lines += ["", "## 남은 실제 검증", ""] + [f"- `{item}`" for item in report["unverified"]]
    lines += ["", "비밀값·문자 내용·전화번호·원본 오류는 보고서에 포함하지 않습니다. 배포·발송·유료 API 호출을 실행하지 않습니다."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output/message-review-deployment")
    parser.add_argument("--delivery", action="store_true", help="기존 worker·예약·Telegram 참조 메타데이터도 조회")
    args = parser.parse_args(argv)
    try:
        report = audit(args.project)
        if args.delivery:
            report["delivery_preflight"] = delivery_metadata(args.project)
    except ValueError:
        print("GCP 프로젝트 설정을 확인해 주세요. 점검을 실행하지 않았습니다.")
        return 2
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (args.output_dir / "summary.md").write_text(markdown(report))
    print("메타데이터 점검 보고서를 저장했습니다. 실제 연결 동작 검증은 별도입니다.")
    return 0 if report["audit_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
