"""Read a small sanitized response from the fixed IAM-private probe service."""
import json
import os
from pathlib import Path
import re
import urllib.request
from urllib.parse import urlsplit


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def main():
    parsed = urlsplit(os.environ["CHECK_URL"])
    if parsed.scheme != "https" or not re.fullmatch(r"message-feed-check-[0-9]+-(?:[a-z0-9-]+\.a|531222653541\.asia-northeast3)\.run\.app", parsed.hostname or "") or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("invalid_probe_url")
    report = {"status": "blocked", "reason": "private_probe_unavailable"}
    try:
        request = urllib.request.Request(os.environ["CHECK_URL"]+"/verify", data=b"", method="POST",
                    headers={"Authorization": "Bearer "+os.environ["CHECK_ID_TOKEN"]})
        with urllib.request.build_opener(NoRedirect).open(request, timeout=165) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError("large_response")
        report = json.loads(raw)
    except Exception:
        pass
    out = Path("safetydata-runtime-check")
    out.mkdir(exist_ok=True)
    (out/"report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    print("Runtime probe:", report.get("status"))
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
