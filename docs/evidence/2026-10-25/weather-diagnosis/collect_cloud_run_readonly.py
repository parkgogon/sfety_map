"""Cloud Shell에서 API/Worker의 Cloud Run 설정 메타데이터만 읽는다.

애플리케이션 URL/Worker/dispatch 경로에 접속하거나 실행하지 않는다.
배포·설정 변경·Secret 값 조회 없이 이름/리비전/네트워크/프록시 존재 여부만 출력한다.
"""
from __future__ import annotations
import argparse
import json
import shutil
import subprocess

NETWORK_KEYS = (
    "run.googleapis.com/vpc-access-connector",
    "run.googleapis.com/vpc-access-egress",
    "run.googleapis.com/network-interfaces",
    "run.googleapis.com/ingress",
)
PROXY_NAMES = {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
               "http_proxy", "https_proxy", "all_proxy", "no_proxy"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="keco-safety-map")
    parser.add_argument("--region", default="asia-northeast3")
    args = parser.parse_args()
    if not shutil.which("gcloud"):
        parser.error("Cloud Shell 등 gcloud 조회 계정이 있는 환경에서 실행하세요.")
    results = []
    for name in ("safety-dashboard-api", "safety-alert-worker"):
        command = ["gcloud", "run", "services", "describe", name,
                   "--project", args.project, "--region", args.region, "--format=json"]
        process = subprocess.run(command, capture_output=True, text=True, timeout=45)
        if process.returncode:
            # stderr 원문이나 환경 변수 전체를 출력하지 않는다.
            results.append({"service": name, "querySucceeded": False,
                            "exitCode": process.returncode})
            continue
        service = json.loads(process.stdout)
        template = service.get("spec", {}).get("template", {})
        annotations = template.get("metadata", {}).get("annotations", {})
        spec = template.get("spec", {})
        containers = spec.get("containers", [])
        environment = containers[0].get("env", []) if containers else []
        kma = next((v for v in environment if v.get("name") == "KMA_API_KEY"), {})
        reference = kma.get("valueFrom", {}).get("secretKeyRef", {})
        results.append({
            "service": name, "querySucceeded": True,
            "latestReadyRevision": service.get("status", {}).get("latestReadyRevisionName"),
            "serviceAccount": spec.get("serviceAccountName"),
            "networkAnnotations": {key: annotations.get(key) for key in NETWORK_KEYS},
            "networkAnnotationNote": "Null is only an absent annotation; inspect inherited VPC/firewall/NAT policies separately.",
            "proxyVariableNamesPresent": sorted(v["name"] for v in environment if v.get("name") in PROXY_NAMES),
            "kmaKeyConfigured": bool(kma),
            "kmaSecretReference": {"name": reference.get("name"), "version": reference.get("key")},
        })
    print(json.dumps({"scope": "Read-only Cloud Run control-plane descriptions; no app/Worker/dispatch calls or secret values.",
                      "project": args.project, "region": args.region,
                      "services": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
