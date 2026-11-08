"""Read only current Cloud Run revisions and the last Hosting release, without values."""
import datetime as dt
import json
from pathlib import Path
import subprocess
import urllib.request

PROJECT = "keco-safety-map"


def main():
    out=Path("release-check");out.mkdir(exist_ok=True)
    result={"checked_at":dt.datetime.now(dt.timezone.utc).isoformat(),"services":{},"hosting":None}
    for name in ("safety-dashboard-api","safety-alert-worker"):
        r=subprocess.run(["gcloud","run","services","describe",name,"--project",PROJECT,"--region","asia-northeast3",
            "--format=json(status.latestReadyRevisionName,status.traffic,spec.template.spec.containers.image)"],capture_output=True,text=True,timeout=30)
        if r.returncode: raise RuntimeError("service_baseline_unavailable")
        value=json.loads(r.stdout)
        result["services"][name]={"revision":value["status"]["latestReadyRevisionName"],"traffic":value["status"].get("traffic",[]),
            "images":[c["image"] for c in value.get("spec",{}).get("template",{}).get("spec",{}).get("containers",[])]}
    try:
        r=subprocess.run(["gcloud","auth","print-access-token","--quiet"],capture_output=True,text=True,timeout=30,check=True)
        request=urllib.request.Request("https://firebasehosting.googleapis.com/v1beta1/sites/keco-safety-map/releases?pageSize=1",headers={"Authorization":"Bearer "+r.stdout.strip()})
        with urllib.request.urlopen(request,timeout=20) as response:value=json.load(response)
        release=value.get("releases",[])[0]
        result["hosting"]={"release":release.get("name"),"version":release.get("version",{}).get("name"),"release_time":release.get("releaseTime")}
    except Exception:result["hosting_status"]="metadata_unavailable"
    (out/"baseline.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print("복구용 리비전/Hosting 메타데이터를 저장했습니다. 비밀값은 포함하지 않습니다.")


if __name__=="__main__":main()
