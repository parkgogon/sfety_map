"""One-shot production browser check. Credentials stay inside the Cloud Run task."""
from __future__ import annotations

import base64
import json
import os
import re
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
            return bool(re.fullmatch(r"/internal/v1/message-records(?:/(?:status|manual-[a-f0-9]{32})(?:/(?:analyze|spatial|reference|facilities|selection|related|review|complete|notice-copy))?)?", path)) and method in ("GET", "POST")
        return method == "GET"
    return method == "GET" and bool(re.fullmatch(r"(?:[a-z0-9-]+\.)*(?:kakao\.com|kakaocdn\.net|daumcdn\.net|kakao\.net)", parsed.hostname or ""))


def emit(value):
    print(json.dumps({"release_check": True, **value}, ensure_ascii=False), flush=True)


def verify(sink=emit):
    password = os.environ.get("ADMIN_ACCESS_PASSWORD", "")
    revision = os.environ.get("VERIFY_APP_REVISION", "")
    resume = os.environ.get("VERIFY_RECORD_ID", "")
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
            def api(path):
                return page.evaluate("""async path => {
                    const response = await fetch(path, {redirect:'error', signal:AbortSignal.timeout(20000),
                        headers:{'X-Alert-Admin-Token':sessionStorage.getItem('keco_admin_token') || ''}});
                    if (response.status !== 200) throw new Error('protected_read');
                    return response.json();
                }""", path)
            page.goto(BASE+"/control/messages"+("?record_id="+resume if resume else ""),wait_until="networkidle",timeout=60000)
            phase="login"
            page.get_by_label("관리자 비밀번호",exact=True).fill(password)
            page.get_by_role("button",name="로그인",exact=True).click()
            page.get_by_role("heading",name="등록한 재난문자",exact=True).wait_for()
            assert api("/internal/v1/message-records/status")["storage_mode"]=="firestore"
            status=api("/internal/v1/message-analysis/status")
            assert status["configured"] and status["place_search_configured"]
            operation=api("/internal/v1/notifications/status")
            sink({"kind":"operations","status":{key:value for key,value in operation.items() if key in ("kma_health","kma_failure_category","kma_consecutive_errors","last_result","last_run_at","kma_last_success_at","kma_failure_started_at") and isinstance(value,(str,int))}})
            asset = page.locator('script[type="module"][src]').first.get_attribute("src")
            assert asset and asset.startswith("/assets/")
            assert revision in page.evaluate("path=>fetch(path,{redirect:'error'}).then(r=>r.text())",asset)
            phase="register"
            if resume:
                identifier=resume
                record=api("/internal/v1/message-records/"+identifier)
                assert record["origin"]=="example" and record["message"]["source"]==SOURCE
            else:
                page.get_by_role("button",name="사고 발생",exact=True).click()
                page.get_by_label("발신처·출처",exact=True).fill(SOURCE)
                page.get_by_label("문자 수신지역",exact=True).fill("대구광역시 달서구")
                page.get_by_role("button",name="문자 등록",exact=True).click()
                page.get_by_role("button",name="저장된 문자 분석",exact=True).wait_for()
                identifier=parse_qs(urlsplit(page.url).query)["record_id"][0]
                record=api("/internal/v1/message-records/"+identifier)
            sink({"kind":"checkpoint","phase":"registered","record_id":identifier})
            phase="analysis"
            if not record.get("analysis"):
                page.get_by_role("button",name="저장된 문자 분석",exact=True).click()
            spatial=page.get_by_role("region",name="지도 확인과 업무 대상 시설 선정",exact=True)
            review=page.get_by_role("region",name="검토 결과와 안내 초안",exact=True)
            spatial.wait_for(timeout=120000)
            record=api("/internal/v1/message-records/"+identifier)
            assert record["analysis_state"]=="completed" and 0 < record["analysis"]["model_calls"] <= 6
            assert record["origin"]=="example"
            if record["review_state"] != "completed":
                phase="reference"
                spatial.get_by_role("button",name=re.compile("후보 선택$")).first.click()
                spatial.get_by_label("기준점 확인 근거",exact=True).fill("창작 배포 검수: 산업단지 대표점을 참고 기준으로 사용")
                spatial.get_by_role("checkbox",name="이 위치와 거리를 참고 조회 기준으로 확인했습니다.",exact=True).check()
                spatial.get_by_role("button",name="이 기준점으로 조회",exact=True).click()
                spatial.locator('.message-selection-list input[type="checkbox"]').first.wait_for()
                page.wait_for_function("typeof kakao !== 'undefined' && typeof kakao.maps.Map === 'function'")
                phase="selection"
                spatial.locator('.message-selection-list input[type="checkbox"]').first.check()
                spatial.get_by_label("시설 선정 사유",exact=True).fill("운영 배포 검수용 창작 기록이며 실제 점검 대상 지정이 아님")
                spatial.get_by_role("button",name="선정 시설 저장",exact=True).click()
                spatial.get_by_text("업무 대상 시설 선정을 저장했습니다.",exact=True).wait_for()
                phase="complete"
                review.get_by_label("검토 완료 사유",exact=True).fill("운영 배포 검수용 창작 시나리오의 저장/조회/초안을 확인함")
                review.get_by_label("확인 질문 보완 메모",exact=True).fill("실제 사고·현장 확인이 아님. 대표점 주변 참고 조회와 업무 흐름만 검수함.")
                for field in review.locator('textarea[aria-label$="미선정 사유"]').all(): field.fill("창작 배포 검수 범위 밖으로 별도 확인하지 않음")
                review.get_by_role("button",name="검토 완료하고 초안 만들기",exact=True).click()
            review.get_by_label("저장한 안내 초안",exact=True).wait_for()
            phase="restore"
            page.reload(wait_until="networkidle")
            review.get_by_label("저장한 안내 초안",exact=True).wait_for()
            saved=api("/internal/v1/message-records/"+identifier)
            assert saved["review_state"]=="completed" and saved["review_completion"]["selected_unique_count"]>=1
            assert SOURCE in saved["notice_draft"]["text"] and "창작 예문" in saved["notice_draft"]["text"]
            assert api("/internal/v1/message-records/"+identifier+"/review")["draft_current"]
            phase="clipboard"
            review.get_by_role("button",name="현재 초안 복사",exact=True).click()
            review.get_by_text("초안을 클립보드에 복사했습니다. 실제 발송·수신 기록은 아닙니다.",exact=True).wait_for()
            assert page.evaluate("navigator.clipboard.readText()") == saved["notice_draft"]["text"]
            phase="screenshots"
            page.wait_for_function("typeof kakao !== 'undefined' && typeof kakao.maps.Map === 'function'")
            for name,width,height in (("desktop",1440,1050),("mobile",390,844)):
                page.set_viewport_size({"width":width,"height":height})
                page.evaluate("scrollTo(0,document.querySelector('.message-spatial').getBoundingClientRect().top+scrollY-80)")
                page.wait_for_timeout(400)
                assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                raw=page.screenshot(type="jpeg",quality=70)
                if len(raw)>170000: raw=page.screenshot(type="jpeg",quality=45)
                assert len(raw)<180000
                sink({"kind":"screenshot","name":name,"jpeg_base64":base64.b64encode(raw).decode()})
            map_images=page.locator('.message-spatial img').evaluate_all("""images=>images.filter(img=>{
                const u=new URL(img.currentSrc || img.src,location.href);
                return img.complete && img.naturalWidth>=128 &&
                    ((u.hostname==='mts.kakaocdn.net' && u.pathname.startsWith('/api/v1/tile/')) ||
                     (/^map[0-9]*\\.daumcdn\\.net$/.test(u.hostname) && ['2d','sky','hybrid'].some(kind=>u.pathname.startsWith('/map_'+kind))));
            }).length""")
            assert not denied and not errors and len(analysis_requests)<=1 and map_images
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
