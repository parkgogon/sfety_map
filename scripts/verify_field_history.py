"""Production smoke test that reports aggregates only. The sole mutation is admin login."""
import csv
import datetime as dt
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import json
import logging
import os
from urllib.parse import urlsplit
import requests

BASE = "https://keco-safety-map.web.app"
HISTORY = "/internal/v1/notifications/history"
ADMIN = "/internal/v1/admin/access"
DELIVERY = "/internal/v1/message-records/notifications/status"
KST = dt.timezone(dt.timedelta(hours=9))


def verify():
    phase = "authentication"
    session = requests.Session()
    try:
        today = dt.datetime.now(KST).date()
        query = {"from": (today - dt.timedelta(days=6)).isoformat(), "to": today.isoformat()}
        assert session.get(BASE + HISTORY, params=query, timeout=20).status_code == 403
        auth = session.post(BASE + ADMIN, json={"password": os.environ["ADMIN_ACCESS_PASSWORD"]}, timeout=20)
        auth.raise_for_status()
        assert auth.json()["status"] == "ok"
        session.headers["X-Alert-Admin-Token"] = auth.json()["token"]
        phase = "history"
        summary = session.get(BASE + HISTORY, params=query, timeout=45)
        summary.raise_for_status()
        data = summary.json()
        rows = data["events"]
        assert summary.headers.get("Cache-Control") == "private, no-store"
        assert all(dt.datetime.fromisoformat(r["processed_at"]).astimezone(KST).date().isoformat() >= query["from"] for r in rows)
        sent = {s: sum(r["source"] == s and r["status"] == "SENT" and not r["drill"] for r in rows)
                for s in ("automatic", "manual", "disaster")}
        assert all(n == data["sent"].get(s, 0) for s, n in sent.items())
        exported = session.get(BASE + HISTORY, params={**query, "format": "csv"}, timeout=45)
        exported.raise_for_status()
        records = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
        assert [(r["출처"], r["전파 ID"]) for r in records] == [(r["source"], r["id"]) for r in rows]
        phase = "browser"
        with_browser(session.headers["X-Alert-Admin-Token"])
        phase = "delivery"
        status = session.get(BASE + DELIVERY, timeout=20)
        status.raise_for_status()
        value = status.json()
        worker = value.get("worker") or {}
        return {"status": "passed", "checked_at": dt.datetime.now(KST).isoformat(),
                "history_count": len(rows), "sent": sent, "csv_count": len(records),
                "browser_widths": [1366, 390],
                "delivery": {"active": value.get("active"), "state": value.get("state"),
                             "worker_state": worker.get("state"), "worker_at": worker.get("at"),
                             "revision": worker.get("revision"), "worker_stale": value.get("worker_stale")},
                "control_requests": 0, "test_messages_sent": 0}
    except Exception as exc:
        return {"status": "blocked", "phase": phase, "error_type": type(exc).__name__,
                "control_requests": 0, "test_messages_sent": 0}


def with_browser(token):
    from playwright.sync_api import sync_playwright, expect

    allowed = {"/api/v1/monitoring", "/internal/v1/admin/session",
               "/internal/v1/notifications/overview", HISTORY}
    errors = []

    def route(request):
        target = urlsplit(request.request.url)
        path = target.path
        if (target.scheme == "https" and target.hostname == "keco-safety-map.web.app"
            and request.request.method == "GET"
            and (path in allowed or path == "/control" or path.startswith("/assets/"))):
            request.continue_()
        else:
            request.abort()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/chromium", headless=True,
                                    args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(timezone_id="UTC", service_workers="block")
        context.add_init_script(script="sessionStorage.setItem(\"keco_admin_token\", " + json.dumps(token) + ");")
        context.route("**/*", route)
        page = context.new_page()
        page.on("pageerror", lambda _: errors.append(True))
        page.goto(BASE + "/control", wait_until="domcontentloaded", timeout=35000)
        page.get_by_role("button", name="실적·이력", exact=True).click(timeout=30000)
        for width in (1366, 390):
            page.set_viewport_size({"width": width, "height": 900})
            expect(page.locator(".history-report-heading")).to_contain_text(dt.datetime.now(KST).date().isoformat(), timeout=30000)
            expect(page.get_by_role("button", name="CSV 내보내기")).to_be_visible()
        browser.close()
    assert not errors


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        if self.path != "/verify" or self.headers.get("Content-Length", "0") != "0":
            self.send_error(400)
            return
        result = json.dumps(verify()).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(result)))
        self.end_headers()
        self.wfile.write(result)


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    HTTPServer(("0.0.0.0", int(os.getenv("PORT", "8080"))), Handler).serve_forever()
