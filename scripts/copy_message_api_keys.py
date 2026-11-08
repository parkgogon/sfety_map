"""Explicit, one-time GitHub-to-Secret-Manager copy; no key logging or deployment."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
from pathlib import Path

PROJECT = "keco-safety-map"
PROJECT_NUMBER = "531222653541"
TARGETS = {"openai": ("OPENAI_API_KEY",), "kakao": ("KAKAO_REST_API_KEY",),
           "both": ("OPENAI_API_KEY", "KAKAO_REST_API_KEY")}


def copy_keys(env, target="both", *, execute=False, run=subprocess.run):
    if target not in TARGETS:
        raise ValueError("복사 대상 설정을 확인해 주세요.")
    names = TARGETS[target]
    report = {"project": PROJECT, "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "executed": execute, "results": [{"secret": name, "status": "not_attempted", "version": None} for name in names]}
    if not execute:
        return report
    values = {}
    for name in names:
        value = env.get(name, "").strip()
        if not value or len(value) > 4096 or any(c in value for c in ("\n", "\r", "\0")):
            raise ValueError(f"GitHub secret {name}의 등록 상태를 확인해 주세요.")
        values[name] = value
    # Keys travel only through stdin, not command arguments, child env, or files.
    child_env = {key: value for key, value in env.items() if key not in TARGETS["both"]}
    child_env.update(CLOUDSDK_CORE_MAX_HTTP_RETRIES="0", CLOUDSDK_CORE_LOG_HTTP="false",
                     CLOUDSDK_CORE_DISABLE_FILE_LOGGING="true", CLOUDSDK_CORE_DISABLE_PROMPTS="1")
    for row in report["results"]:
        name = row["secret"]
        try:
            response = run(["gcloud", "secrets", "versions", "add", name, "--project", PROJECT,
                            "--data-file=-", "--format=value(name)", "--quiet", "--verbosity=error"],
                           input=values[name], text=True, capture_output=True, timeout=40, check=False, env=child_env)
        except (OSError, subprocess.TimeoutExpired):
            row.update(status="outcome_unknown", reason="owner_version_check_required")
            break
        if response.returncode:
            denied = any(code in response.stderr.upper() for code in ("PERMISSION_DENIED", "NOT_FOUND"))
            row.update(status="request_denied" if denied else "outcome_unknown", reason="owner_version_check_required")
            break
        match = re.fullmatch(r"projects/(?:" + PROJECT + "|" + PROJECT_NUMBER + r")/secrets/" + name + r"/versions/([1-9][0-9]*)", response.stdout.strip())
        if not match:
            row.update(status="outcome_unknown", reason="owner_version_check_required")
            break
        row.update(status="version_created", version=match[1])
    return report


def markdown(report):
    lines = ["# 재난문자 API 키 등록 결과", "",
        "| Secret | 결과 | 생성한 버전 |", "| --- | --- | --- |"]
    lines += [f"| {r['secret']} | {r['status']} | {r['version'] or '-'} |" for r in report["results"]]
    lines += ["", "키 값은 출력하거나 artifact에 저장하지 않습니다. 생성 버전은 배포 설정에 자동 반영하지 않습니다.",
        "일부 실패·결과 미확인은 소유자 계정에서 버전 목록을 확인한 뒤 미등록 대상만 다시 실행하세요.",
        "이 작업은 원본 GitHub secret 삭제·키 재발급·기존 버전 변경/삭제·실제 서비스 호출·배포·발송을 하지 않습니다."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=list(TARGETS), default="both")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("output/message-key-copy"))
    args = parser.parse_args(argv)
    try:
        report = copy_keys(os.environ, args.target, execute=args.execute)
    except ValueError as error:
        print(str(error))
        return 2
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (args.output_dir / "summary.md").write_text(markdown(report))
    print("키 값을 제외한 결과 보고서를 저장했습니다.")
    return 0 if not args.execute or all(r["status"] == "version_created" for r in report["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
