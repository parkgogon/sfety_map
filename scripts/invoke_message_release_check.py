"""Invoke an IAM-protected temporary verifier; credentials never enter artifacts."""
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request
from urllib.parse import urlsplit


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def main():
    url=os.environ["CHECK_URL"]
    parsed=urlsplit(url)
    if parsed.scheme!="https" or not re.fullmatch(r"message-review-check-[0-9]+-(?:[a-z0-9-]+\.a|531222653541\.asia-northeast3)\.run\.app",parsed.hostname or "") or parsed.path or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ValueError("verification_url")
    token=subprocess.run(["gcloud","auth","print-identity-token","--audiences="+url,"--quiet"],capture_output=True,text=True,timeout=30,check=True).stdout.strip()
    request=urllib.request.Request(url+"/verify",data=b"",method="POST",headers={"Authorization":"Bearer "+token})
    with urllib.request.build_opener(NoRedirect).open(request,timeout=330) as response:payload=json.load(response)
    out=Path("release-check");out.mkdir(exist_ok=True)
    result={"service":parsed.hostname,"verification_exit_code":payload["exit_code"]}
    for data in payload.get("rows",[]):
        if data.get("kind")=="checkpoint" and re.fullmatch(r"manual-[a-f0-9]{32}",data.get("record_id","")):
            result["record_id"]=data["record_id"]
        if data.get("kind")=="screenshot" and data.get("name") in ("desktop","mobile"):
            raw=base64.b64decode(data.get("jpeg_base64",""),validate=True)
            if raw.startswith(b'\xff\xd8') and len(raw)<180000:(out/(data["name"]+".jpg")).write_bytes(raw)
        if data.get("kind")=="result":
            result["browser"]={k:data[k] for k in ("status","phase","record_id","source_revision","model_calls","selected_count","analysis_requests","tile_responses","page_errors","unexpected_requests","real_messages_sent","error_type","denied_hosts") if k in data}
    (out/"verification.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print("비공개 검수 결과를 저장했습니다. 비밀값은 포함하지 않습니다.")
    return 0 if result.get("browser",{}).get("status")=="passed" and payload["exit_code"]==0 else 1


if __name__=="__main__":raise SystemExit(main())
