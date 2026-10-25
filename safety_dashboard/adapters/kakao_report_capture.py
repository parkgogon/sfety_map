"""고정된 보고서 지도 페이지를 실제 Chromium으로 한 장 캡처한다."""
from __future__ import annotations

import asyncio
import hashlib
import os
import threading
from urllib.parse import urlsplit

from safety_dashboard.application.nearby_map import NearbyMapResult
from safety_dashboard.application.nearby_report import NearbyReport
from safety_dashboard.application.nearby_report_summary import capture_input

SDK_HOSTS = frozenset({"dapi.kakao.com", "t1.kakaocdn.net", "mts.kakaocdn.net"})


class KakaoReportCapture:
    def __init__(self, *, enabled: bool, origin: str, executable: str = "/usr/bin/chromium", timeout: int = 20):
        parsed = urlsplit(origin)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
            raise ValueError("보고서 지도 원점은 HTTPS 사이트 주소여야 합니다.")
        self.origin = origin.rstrip("/")
        self.enabled, self.executable, self.timeout = enabled, executable, timeout
        self._slot = threading.Lock()

    async def capture(self, report: NearbyReport) -> NearbyMapResult:
        if not self.enabled:
            return NearbyMapResult("unavailable")
        if not self._slot.acquire(blocking=False):
            return NearbyMapResult("busy")
        try:
            try:
                async with asyncio.timeout(self.timeout):
                    return await self._capture(report)
            except TimeoutError:
                return NearbyMapResult("timeout")
            except asyncio.CancelledError:
                raise
            except Exception:
                # SDK URL/응답/브라우저 예외에는 키가 포함될 수 있어 원문을 기록하지 않는다.
                return NearbyMapResult("unavailable")
        finally:
            self._slot.release()

    async def _prepare_page(self, page):
        """운영은 실제 정적 페이지를 연다. 개발 검수는 이 지점에서 로컬 응답을 주입한다."""
        await page.goto(self.origin + "/report-map.html", wait_until="domcontentloaded")

    async def _capture(self, report: NearbyReport) -> NearbyMapResult:
        from playwright.async_api import async_playwright

        payload = capture_input(report, "report")
        proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
        options = {"executable_path": self.executable, "headless": True, "args": ["--no-sandbox"]}
        if proxy_url:
            options["proxy"] = {"server": proxy_url}
        async with async_playwright() as driver:
            browser = await driver.chromium.launch(**options)
            try:
                context = await browser.new_context(viewport={"width": 1200, "height": 620}, device_scale_factor=2,
                                                    locale="ko-KR", accept_downloads=False, service_workers="block")
                async def guard(route):
                    request = route.request
                    parsed = urlsplit(request.url)
                    request_origin = f"{parsed.scheme}://{parsed.netloc}"
                    own_asset = request_origin == self.origin and (parsed.path == "/report-map.html" or parsed.path.startswith("/assets/"))
                    sdk_asset = parsed.scheme == "https" and parsed.hostname in SDK_HOSTS
                    if request.method != "GET" or not (own_asset or sdk_asset):
                        return await route.abort()
                    await route.continue_()
                await context.route("**/*", guard)
                page = await context.new_page()
                page.set_default_timeout(self.timeout * 1000)
                await self._prepare_page(page)
                await page.wait_for_function("window.nearbyMapVersion === 1 && typeof window.renderReportMap === 'function'")
                geometry = await page.evaluate("data => window.renderReportMap(data)", payload)
                await page.wait_for_function("""() => {
                    const el=document.getElementById('map'),r=el.getBoundingClientRect();
                    const tile=document.elementsFromPoint(r.width/2,r.height/2).find(e=>e.tagName==='IMG'&&e.src.includes('/tile/'));
                    if(!tile)return false;
                    const imgs=[...tile.parentElement.querySelectorAll('img')].filter(i=>{const b=i.getBoundingClientRect();return i.src.includes('/tile/')&&b.right>0&&b.left<r.width&&b.bottom>0&&b.top<r.height});
                    return imgs.length>0&&imgs.every(i=>i.complete&&i.naturalWidth>0);
                }""")
                layout = await page.evaluate("""() => {
                    const labels=[...document.querySelectorAll('.badge')].map(e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}});
                    return {clipped:labels.some(b=>b.x<0||b.y<0||b.x+b.w>1200||b.y+b.h>590),
                        overlaps:labels.some((a,i)=>labels.slice(i+1).some(b=>a.x<b.x+b.w&&a.x+a.w>b.x&&a.y<b.y+b.h&&a.y+a.h>b.y))};
                }""")
                if layout["clipped"] or layout["overlaps"] or any(not 0 <= p["x"] <= 1200 or not 45 <= p["y"] <= 590 for p in geometry["circlePixels"]):
                    return NearbyMapResult("unavailable")
                png = await page.locator("#map").screenshot(type="png", animations="disabled")
                metadata = dict(payload, geometry=geometry, pngSha256=hashlib.sha256(png).hexdigest())
                return NearbyMapResult("captured", png, metadata)
            finally:
                await browser.close()
