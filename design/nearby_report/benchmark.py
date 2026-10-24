"""로컬 1 CPU affinity에서 기존 API와 지도 캡처의 병행 비용을 측정한다.

Cloud Run/컨테이너/실제 운영 부하 검증이 아니다. API는 TestClient와 NetworkGuard로
격리하고 지도 캡처 프로세스만 실제 SDK/타일을 환경 프록시로 조회한다.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
from unittest.mock import Mock

from fastapi.testclient import TestClient
from safety_dashboard.api.app import create_app
from scripts.test_support import NetworkGuard

ROOT = Path(__file__).resolve().parents[2]


def stats(values):
    ordered = sorted(values)
    return {"samples": len(values), "medianMs": round(statistics.median(values), 1),
            "p95Ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * .95))], 1),
            "maxMs": round(max(values), 1)}


def memory_pss():
    text = Path(f"/proc/{os.getpid()}/smaps_rollup").read_text()
    return round(float(next(line.split()[1] for line in text.splitlines() if line.startswith("Pss:"))) / 1024, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    cpu = min(os.sched_getaffinity(0))
    os.sched_setaffinity(0, {cpu})  # 자신과 자식 프로세스만 고정, 전역 CPU 설정은 변경하지 않는다.
    monitoring = Mock()
    monitoring.snapshot.side_effect = AssertionError("No KMA/monitoring snapshot during benchmark")
    body = {"latitude": 35.8714, "longitude": 128.6014, "label": "로컬 성능 검수", "address": "대구 중구", "radius_km": 5}
    results = {"scope": "Local Linux processes pinned to one logical CPU; in-process API with network guard. No Cloud Run memory limit/cold start/production load verification.", "cpuAffinityCount": 1}
    with NetworkGuard() as guard, TestClient(create_app(service=monitoring)) as client:
        def measure():
            start = time.perf_counter()
            response = client.get("/api/v1/health")
            assert response.status_code == 200
            health = (time.perf_counter() - start) * 1000
            start = time.perf_counter()
            response = client.post("/api/v1/reports/nearby.pdf", json=body)
            assert response.status_code == 200 and response.content.startswith(b"%PDF")
            assert response.headers["X-Nearby-Facility-Count"] == "3"
            return health, (time.perf_counter() - start) * 1000
        measure()  # 폰트·모듈 초기화는 기준 측정에서 제외한다.
        before = [measure() for _ in range(8)]
        results["apiProcessPssMiB"] = memory_pss()
        child_env = os.environ.copy()
        child_env.update(NEARBY_PREVIEW_DIR=str(args.directory / "capture"), PYTHON=sys.executable,
                         NEARBY_CASES="urban-5km,urban-50km,synthetic-dense-long")
        with (args.directory / "capture.log").open("w") as log:
            child = subprocess.Popen(["node", "design/nearby_report/capture.mjs"], cwd=ROOT, env=child_env,
                                     stdout=log, stderr=subprocess.STDOUT)
            try:
                during = []
                while child.poll() is None:
                    during.append(measure())
                if child.wait() != 0:
                    raise RuntimeError("Capture failed; inspect sanitized results/log locally")
            finally:
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=10)
        guard.assert_unused()
        monitoring.snapshot.assert_not_called()
        results.update(baselineHealth=stats([r[0] for r in before]), baselinePdf=stats([r[1] for r in before]),
                       concurrentHealth=stats([r[0] for r in during]), concurrentPdf=stats([r[1] for r in during]),
                       externalApiAttempts=guard.attempts)
    capture = json.loads((args.directory / "capture/capture-results.json").read_text())
    results["captureMs"] = [row["captureMs"] for row in capture["records"]]
    results["peakBrowserPssMiB"] = capture["peakBrowserPssMiB"]
    (args.directory / "benchmark-results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main()
