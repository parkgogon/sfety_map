"""One-shot production browser check. Credentials stay inside the Cloud Run task."""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

BASE = "https://keco-safety-map.web.app"
SOURCE = "운영 배포 검수 · 창작 예문"


def is_map_tile(url):
    parsed=urlsplit(url)
    return parsed.scheme=="https" and bool(
        parsed.hostname=="mts.kakaocdn.net" and parsed.path.startswith("/api/v1/tile/")
        or re.fullmatch(r"map[0-9]*\.daumcdn\.net",parsed.hostname or "") and re.match(r"/map_(?:2d|sky|hybrid)",parsed.path))


def allowed_request(url, method):
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.port not in (None, 443) or parsed.username or parsed.password: return False
    except ValueError: return False
    if parsed.hostname == "keco-safety-map.web.app":
        path = parsed.path
        if path.startswith("/api/"): return False
        if path.startswith("/internal/"):
            if path in ("/internal/v1/admin/session", "/internal/v1/message-analysis/status", "/internal/v1/notifications/status"): return method == "GET"
            if path == "/internal/v1/admin/access": return method == "POST"
            if path in ("/internal/v1/message-records/status", "/internal/v1/message-records/automation"):
                return method == "GET"
            if path == "/internal/v1/message-records": return method in ("GET", "POST")
            return bool(re.fullmatch(r"/internal/v1/message-records/manual-[a-f0-9]{32}(?:/(?:spatial|reference|facilities|selection|related|review|notice-copy|prepare|approve|hold|reopen))?", path)) and method in ("GET", "POST")
        return method == "GET"
    return method == "GET" and bool(re.fullmatch(r"(?:[a-z0-9-]+\.)*(?:kakao\.com|kakaocdn\.net|daumcdn\.net|kakao\.net)", parsed.hostname or ""))


def emit(value):
    print(json.dumps({"release_check": True, **value}, ensure_ascii=False), flush=True)


def enqueue_verification_example(record, store, now):
    """Only the explicitly tagged synthetic record may enter the production queue."""
    from safety_dashboard.application.message_pipeline import MessageAnalysisQueue
    if record.get("origin") != "example" or record.get("message", {}).get("source") != SOURCE:
        raise ValueError("verification_example_required")
    return MessageAnalysisQueue(store).enqueue(record, now)


def automation_summary(value):
    # Do not export raw records, model output, source text or arbitrary status fields.
    return {key: value[key] for key in ("state", "auto_collection_enabled", "feed_configured", "interval_seconds", "last_attempt_at", "last_success_at", "start_at", "queue", "budget", "feed_budget", "remaining_partitions", "skipped_rows", "coverage_gap") if key in value}


def verify(sink=emit):
    password = os.environ.get("ADMIN_ACCESS_PASSWORD", "")
    revision = os.environ.get("VERIFY_APP_REVISION", "")
    resume = os.environ.get("VERIFY_RECORD_ID", "")
    read_only = os.environ.get("VERIFY_READ_ONLY") == "true"
    if not password or not re.fullmatch(r"[a-f0-9]{40}", revision) or resume and not re.fullmatch(r"manual-[a-f0-9]{32}", resume):
        raise ValueError("verification_configuration")
    from playwright.sync_api import sync_playwright
    phase, identifier = "open", None
    denied, errors, analysis_requests, tiles = [], [], [], []
    map_images=0
    try:
        with sync_playwright() as p:
            fontconfig=Path('/tmp/message-release-fontconfig.conf')
            fontconfig.write_text('<fontconfig><include ignore_missing="yes">/etc/fonts/fonts.conf</include><dir>/app/fonts</dir><cachedir>/tmp/message-release-fontcache</cachedir></fontconfig>')
            browser = p.chromium.launch(executable_path="/usr/bin/chromium",headless=True,args=["--no-sandbox","--disable-dev-shm-usage"],env={**os.environ,"FONTCONFIG_FILE":str(fontconfig)})
            context = browser.new_context(viewport={"width":1440,"height":1050},permissions=["clipboard-read","clipboard-write"])
            page = context.new_page(); page.set_default_timeout(30000)
            page.on("pageerror", lambda _: errors.append("page_error"))
            page.on("response", lambda r: tiles.append(1) if r.status == 200 and is_map_tile(r.url) else None)
            def route(r):
                if not allowed_request(r.request.url,r.request.method):
                    denied.append(urlsplit(r.request.url).hostname);r.abort();return
                if urlsplit(r.request.url).path.endswith("/analyze"): analysis_requests.append(1)
                r.continue_()
            context.route("**/*",route)
            def api(path, body=None):
                return page.evaluate("""async ({path,body}) => {
                    const response = await fetch(path, {redirect:'error', signal:AbortSignal.timeout(20000),
                        method:body===null?'GET':'POST', body:body===null?undefined:JSON.stringify(body),
                        headers:{'Content-Type':'application/json','X-Alert-Admin-Token':sessionStorage.getItem('keco_admin_token') || ''}});
                    if (!response.ok) throw new Error('protected_request');
                    return response.json();
                }""", {"path":path,"body":body})
            page.goto(BASE+"/control/messages"+("?record_id="+resume if resume else ""),wait_until="networkidle",timeout=60000)
            phase="login"
            page.get_by_label("관리자 비밀번호",exact=True).fill(password)
            page.get_by_role("button",name="로그인",exact=True).click()
            page.get_by_role("heading",name="검토 대기함",exact=True).wait_for() if not resume else page.locator('.quick-situation').wait_for()
            assert api("/internal/v1/message-records/status")["storage_mode"]=="firestore"
            status=api("/internal/v1/message-analysis/status")
            assert status["configured"] and status["place_search_configured"]
            automation=api("/internal/v1/message-records/automation")
            sink({"kind":"automation","status":automation_summary(automation)})
            assert automation["auto_collection_enabled"] and automation["feed_configured"]
            assert automation["interval_seconds"]==900 and automation["budget"]["limit"]==20 and automation["feed_budget"]["limit"]==450
            assert automation["state"] in ("starting","live","partial")
            operation=api("/internal/v1/notifications/status")
            sink({"kind":"operations","status":{key:value for key,value in operation.items() if key in ("kma_health","kma_failure_category","kma_consecutive_errors","last_result","last_run_at","kma_last_success_at","kma_failure_started_at") and isinstance(value,(str,int))}})
            asset = page.locator('script[type="module"][src]').first.get_attribute("src")
            assert asset and asset.startswith("/assets/")
            assert revision in page.evaluate("path=>fetch(path,{redirect:'error'}).then(r=>r.text())",asset)
            if read_only:
                assert automation["state"] == "live" and automation["last_success_at"]
                assert automation["feed_budget"]["used"] > 0
                records=api("/internal/v1/message-records")["records"]
                sink({"kind":"result","status":"passed","source_revision":revision,
                      "official_records_in_page":sum(r["origin"]=="official" for r in records),
                      "analyzed_official_records_in_page":sum(r["origin"]=="official" and r["analysis_state"]=="completed" for r in records),
                      "analysis_requests":0,"page_errors":len(errors),"unexpected_requests":len(denied),"real_messages_sent":0})
                assert not denied and not errors
                context.close();browser.close()
                return 0
            phase="register"
            if resume:
                identifier=resume
                record=api("/internal/v1/message-records/"+identifier)
                assert record["origin"]=="example" and record["message"]["source"]==SOURCE
            else:
                # Register only; the browser must not request analysis. The next regular
                # Scheduler execution processes this one clearly labelled example.
                record=api("/internal/v1/message-records",{
                    "registration_key":str(uuid.uuid4()), "input_kind":"example", "source":SOURCE,
                    "issued_at":"2026-11-08T10:10:00+09:00", "recipient_regions":["대구광역시 달서구"],
                    "reference_radius_km":3,
                    "text":"[창작 예문 · 달서구] 오늘 10시 대구 성서산업단지 인근 공장에서 화재 발생. 주변 주민은 연기 유입에 주의하고 창문을 닫아 주세요."})["record"]
                identifier=record["id"]
            sink({"kind":"checkpoint","phase":"registered","record_id":identifier})
            phase="scheduled_analysis"
            if not record.get("analysis"):
                from safety_dashboard.adapters.firestore_message_pipeline import FirestoreMessagePipelineStore
                store=FirestoreMessagePipelineStore("keco-safety-map")
                enqueue_verification_example(record,store,dt.datetime.now(dt.timezone.utc))
                deadline=time.monotonic()+170
                while time.monotonic()<deadline:
                    record=api("/internal/v1/message-records/"+identifier)
                    if record["analysis_state"] in ("completed","failed"):break
                    page.wait_for_timeout(5000)
                from safety_dashboard.application.message_pipeline import task_id
                task=store.get(task_id(record)) or {}
                if task.get("state") != "done":
                    page.wait_for_timeout(1000)
                    task=store.get(task_id(record)) or {}
                sink({"kind":"pipeline","status":{"state":task.get("state"),"attempts":task.get("attempts"),"detail":task.get("detail"),"browser_analysis_requests":len(analysis_requests)}})
                assert task.get("state")=="done" and task.get("attempts")==1
            assert record["analysis_state"]=="completed" and 0 < record["analysis"]["model_calls"] <= 6
            assert record["origin"]=="example"
            page.goto(BASE+"/control/messages?record_id="+identifier,wait_until="networkidle")
            review=page.get_by_role("region",name="한 화면 검토",exact=True)
            if record["review_state"]!="completed":
                review.wait_for()
                review.get_by_label("안내 초안 미리보기",exact=True).wait_for()
                phase="reference"
                # The actual Korean label is kept exact to catch a mismatched UI.
                ack=review.get_by_role("checkbox",name="이 위치와 거리를 참고 조회 기준으로 사용합니다.",exact=True)
                if ack.count(): ack.check()
                phase="complete"
                primary=review.get_by_role("button",name="이 내용으로 검토 완료",exact=True)
                from playwright.sync_api import expect
                expect(primary).to_be_enabled(timeout=30000)
                primary.click()
            page.get_by_label("저장한 안내 초안",exact=True).wait_for()
            phase="restore"
            page.reload(wait_until="networkidle")
            page.get_by_label("저장한 안내 초안",exact=True).wait_for()
            saved=api("/internal/v1/message-records/"+identifier)
            assert saved["review_state"]=="completed" and saved["review_completion"]["selected_unique_count"]>=1
            assert SOURCE in saved["notice_draft"]["text"] and "창작 예문" in saved["notice_draft"]["text"]
            assert api("/internal/v1/message-records/"+identifier+"/review")["draft_current"]
            phase="clipboard"
            page.get_by_role("button",name="안내문 복사",exact=True).click()
            page.get_by_text("안내문을 복사했습니다. 기존 보고·전달에 사용할 수 있습니다.",exact=True).wait_for()
            assert page.evaluate("navigator.clipboard.readText()") == saved["notice_draft"]["text"]
            phase="saved_map"
            # Re-open only the tagged example to inspect the new proposal/map after
            # restoring its saved result; leave it completed at the end.
            page.get_by_role("button",name="내용 보완·다시 검토",exact=True).click()
            review.get_by_label("안내 초안 미리보기",exact=True).wait_for()
            phase="screenshots"
            page.wait_for_function("typeof kakao !== 'undefined' && typeof kakao.maps.Map === 'function'")
            for name,width,height in (("desktop",1440,1050),("mobile",390,844)):
                page.set_viewport_size({"width":width,"height":height})
                page.evaluate("scrollTo(0,document.querySelector('.quick-review').getBoundingClientRect().top+scrollY-80)")
                page.wait_for_timeout(400)
                assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                raw=page.screenshot(type="jpeg",quality=70)
                if len(raw)>170000: raw=page.screenshot(type="jpeg",quality=45)
                assert len(raw)<180000
                sink({"kind":"screenshot","name":name,"jpeg_base64":base64.b64encode(raw).decode()})
            map_images=page.locator('.quick-review img').evaluate_all("""images=>images.filter(img=>{
                const u=new URL(img.currentSrc || img.src,location.href);
                return img.complete && img.naturalWidth>=128 &&
                    ((u.hostname==='mts.kakaocdn.net' && u.pathname.startsWith('/api/v1/tile/')) ||
                     (/^map[0-9]*\\.daumcdn\\.net$/.test(u.hostname) && ['2d','sky','hybrid'].some(kind=>u.pathname.startsWith('/map_'+kind))));
            }).length""")
            assert not denied and not errors and not analysis_requests and map_images
            from playwright.sync_api import expect
            primary=review.get_by_role("button",name="이 내용으로 검토 완료",exact=True)
            expect(primary).to_be_enabled(timeout=30000)
            primary.click()
            page.get_by_label("저장한 안내 초안",exact=True).wait_for()
            sink({"kind":"automation","status":automation_summary(api("/internal/v1/message-records/automation"))})
            sink({"kind":"result","status":"passed","record_id":identifier,"source_revision":revision,
                  "model_calls":saved["analysis"]["model_calls"],"selected_count":saved["review_completion"]["selected_unique_count"],
                  "analysis_requests":len(analysis_requests),"tile_responses":len(tiles),"rendered_map_images":map_images,"page_errors":len(errors),"unexpected_requests":len(denied),"real_messages_sent":0})
            context.close();browser.close()
        return 0
    except Exception as error:
        sink({"kind":"result","status":"failed","phase":phase,"record_id":identifier,"error_type":type(error).__name__,"denied_hosts":sorted(set(denied))[:10],"analysis_requests":len(analysis_requests),"tile_responses":len(tiles),"rendered_map_images":map_images,"page_errors":len(errors),"unexpected_requests":len(denied)})
        return 1


def serve():
    """Cloud Run IAM protects this temporary service; return only sanitized evidence."""
    from http.server import BaseHTTPRequestHandler,HTTPServer
    class Handler(BaseHTTPRequestHandler):
        started=False
        def log_message(self,*args):pass
        def do_POST(self):
            if self.path!="/verify" or Handler.started:
                self.send_error(409);return
            Handler.started=True
            rows=[]
            code=verify(rows.append)
            raw=json.dumps({"exit_code":code,"rows":rows},ensure_ascii=False).encode()
            self.send_response(200);self.send_header("Content-Type","application/json")
            self.send_header("Cache-Control","private, no-store");self.send_header("Content-Length",str(len(raw)))
            self.end_headers();self.wfile.write(raw)
    HTTPServer(("0.0.0.0",int(os.environ.get("PORT","8080"))),Handler).serve_forever()


if __name__ == "__main__":
    if os.environ.get("VERIFY_MODE")=="service":serve()
    else:raise SystemExit(verify())
