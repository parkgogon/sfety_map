"""관리 Docker의 로컬 검수 컨테이너만 시작/확인/종료한다. 배포하지 않는다."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
LABEL = "sfety-map-nearby-integration"


def docker(*args):
    environment = os.environ.copy()
    for key in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
        environment.pop(key, None)
    return subprocess.check_output(["docker", "--host=unix:///var/run/docker.sock", *args], env=environment, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "check", "stop"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    identity = args.directory / "container-id"
    if args.action == "start":
        certificate = os.environ.get("CODEX_PROXY_CERT")
        if not certificate or not Path(certificate).is_file():
            raise RuntimeError("Managed session CA is required")
        if identity.exists():
            raise RuntimeError("Existing QA container identity is preserved; stop that QA container first")
        value = docker("run", "-d", "--label", f"qa-purpose={LABEL}", "--cpus=1", "--memory=1g", "--memory-swap=1g", "--pids-limit=256",
            "-p", "127.0.0.1:8877:8080", "--mount", f"type=bind,src={ROOT}/design/nearby_report/integration_server.py,dst=/qa/integration_server.py,readonly",
            "--mount", f"type=bind,src={ROOT}/field_web/dist,dst=/qa_web,readonly",
            "--mount", f"type=bind,src={certificate},dst=/usr/local/share/ca-certificates/session-proxy.crt,readonly",
            "-e", "PYTHONPATH=/qa", "-e", "NEARBY_QA_WEB=/qa_web", "-e", "NODE_EXTRA_CA_CERTS=/usr/local/share/ca-certificates/session-proxy.crt",
            "sfety-nearby-api:local", "sh", "-c",
            "update-ca-certificates >/dev/null 2>&1 && mkdir -p /root/.pki/nssdb && certutil -d sql:/root/.pki/nssdb -N --empty-password && certutil -d sql:/root/.pki/nssdb -A -n session-proxy -t C,, -i /usr/local/share/ca-certificates/session-proxy.crt && exec uvicorn integration_server:app --host 0.0.0.0 --port 8080 --no-access-log")
        identity.write_text(value)
        from design.nearby_report.integration_checks import request
        for _ in range(40):
            try:
                if request("GET", "/api/v1/health", timeout=1)[0] == 200:
                    print("Local 1 CPU / 1GiB API verification container is ready")
                    return
            except OSError:
                pass
            time.sleep(.25)
        raise RuntimeError("Local QA API did not become ready")
    value = identity.read_text().strip()
    label = docker("inspect", "--format", '{{index .Config.Labels "qa-purpose"}}', value)
    if label != LABEL:
        raise RuntimeError("Only this task's labeled QA container can be managed")
    if args.action == "stop":
        docker("stop", "--time", "10", value)
        docker("rm", value)
        identity.unlink()
        print("Task QA container stopped and removed")
        return
    data = json.loads(docker("inspect", value))[0]
    code = '''from pathlib import Path
from collections import Counter
states=Counter()
for p in Path('/proc').iterdir():
 if not p.name.isdigit():continue
 try:
  lines=(p/'status').read_text().splitlines();name=next(l.split(':',1)[1].strip() for l in lines if l.startswith('Name:'));state=next(l.split()[1] for l in lines if l.startswith('State:'));states[name+' '+state]+=1
 except (OSError,StopIteration):pass
import json
def cgroup(name):
 try:return Path('/sys/fs/cgroup/'+name).read_text().strip()
 except OSError:return None
print(json.dumps({'processes':dict(states),'memoryPeakBytes':cgroup('memory.peak'),'memoryCurrentBytes':cgroup('memory.current'),'memoryEvents':cgroup('memory.events'),'cpuMax':cgroup('cpu.max')}))'''
    observed = json.loads(docker("exec", value, "python", "-c", code))
    result = {"scope":"Local Docker container only; no production deployment", "memoryLimitBytes":data["HostConfig"]["Memory"],
        "memorySwapLimitBytes":data["HostConfig"]["MemorySwap"], "nanoCpus":data["HostConfig"]["NanoCpus"],
        "oomKilled":data["State"]["OOMKilled"], "idleProcesses":observed["processes"],
        "memoryPeakBytes":int(observed["memoryPeakBytes"]) if observed["memoryPeakBytes"] else None,
        "memoryCurrentBytes":int(observed["memoryCurrentBytes"]) if observed["memoryCurrentBytes"] else None,
        "memoryEvents":observed["memoryEvents"],"cpuMax":observed["cpuMax"]}
    (args.directory / "container-limits.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
