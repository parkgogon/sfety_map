"""Collect this task's tagged, sanitized browser report; never print raw task logs."""
import base64
import json
import os
from pathlib import Path
import re
import subprocess


def main():
    out=Path("release-check");out.mkdir(exist_ok=True)
    execution=json.loads((out/"execution.json").read_text())
    name=execution.get("metadata",{}).get("name","").split("/")[-1]
    if not re.fullmatch(r"[a-z0-9-]+",name):raise ValueError("execution_name")
    job=os.environ["CHECK_JOB"]
    if not re.fullmatch(r"message-review-check-[0-9]+",job):raise ValueError("job_name")
    result={"execution":name,"job":job,"conditions":execution.get("status",{}).get("conditions",[]),"logs_status":"unavailable"}
    query=f'resource.type="cloud_run_job" AND resource.labels.job_name="{job}" AND labels."run.googleapis.com/execution_name"="{name}" AND jsonPayload.release_check=true'
    r=subprocess.run(["gcloud","logging","read",query,"--project=keco-safety-map","--limit=40","--order=asc","--format=json"],capture_output=True,text=True,timeout=30)
    if not r.returncode:
        rows=json.loads(r.stdout);result["logs_status"]="observed"
        for row in rows:
            data=row.get("jsonPayload",{})
            if data.get("kind")=="screenshot" and data.get("name") in ("desktop","mobile"):
                raw=base64.b64decode(data.get("jpeg_base64",""),validate=True)
                if raw.startswith(b'\xff\xd8') and len(raw)<180000:(out/(data["name"]+".jpg")).write_bytes(raw)
            if data.get("kind")=="result":
                result["browser"]={k:data[k] for k in ("status","phase","record_id","source_revision","model_calls","selected_count","analysis_requests","tile_responses","page_errors","unexpected_requests","real_messages_sent","error_type","denied_hosts") if k in data}
    (out/"verification.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print("실행 상태와 허용한 검수 결과를 저장했습니다.")


if __name__=="__main__":main()
