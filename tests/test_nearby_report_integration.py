"""실제 네트워크 없이 캡처 동시 제한·취소·실패와 API 연결을 검증한다."""
import asyncio
import hashlib
import io
import threading
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import httpx
from PIL import Image

from safety_dashboard.adapters.kakao_report_capture import KakaoReportCapture
from safety_dashboard.api.app import create_app
from safety_dashboard.api.nearby_reports import NearbyReportBusy, NearbyReportGenerator
from safety_dashboard.application.nearby_map import NearbyMapResult
from safety_dashboard.application.nearby_report import NearbyReport
from safety_dashboard.application.nearby_report_summary import capture_input
from safety_dashboard.domain.models import Facility, GeoPoint

ROOT = Path(__file__).parents[1]


def report():
    point = GeoPoint(35.87, 128.6)
    return NearbyReport.build(point, "검수", "주소", 5, [Facility("a", "검수 시설", "유형", point, "주소", "부서")])


class ControlledCapture(KakaoReportCapture):
    def __init__(self, timeout=20):
        super().__init__(enabled=True, origin="https://keco-safety-map.web.app", timeout=timeout)
        self.started, self.release, self.cleaned = asyncio.Event(), asyncio.Event(), False
    async def _capture(self, value):
        self.started.set()
        try:
            await self.release.wait()
            return NearbyMapResult("unavailable")
        finally:
            self.cleaned = True


class CaptureLimitsTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_capture_and_cancel_releases_slot_after_cleanup(self):
        capture = ControlledCapture()
        first = asyncio.create_task(capture.capture(report()))
        await capture.started.wait()
        self.assertEqual((await capture.capture(report())).status, "busy")
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.assertTrue(capture.cleaned)
        capture.release.set()
        self.assertEqual((await capture.capture(report())).status, "unavailable")

    async def test_timeout_and_sdk_error_become_map_failure(self):
        capture = ControlledCapture(timeout=.01)
        self.assertEqual((await capture.capture(report())).status, "timeout")
        self.assertTrue(capture.cleaned)
        async def sdk_error(_): raise RuntimeError("private SDK URL")
        capture._capture = sdk_error
        self.assertEqual((await capture.capture(report())).status, "unavailable")

    async def test_request_limit_and_recovery_after_cancel(self):
        class Hold:
            async def capture(self, _): await asyncio.Event().wait()
        generator = NearbyReportGenerator(Hold(), ROOT / "fonts/NotoSansKR.ttf")
        tasks = [asyncio.create_task(generator.generate(report())) for _ in range(3)]
        await asyncio.sleep(0)
        with self.assertRaises(NearbyReportBusy):
            await generator.generate(report())
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        generator.capture = KakaoReportCapture(enabled=False, origin="https://keco-safety-map.web.app")
        content, status = await generator.generate(report())
        self.assertTrue(content.startswith(b"%PDF"))
        self.assertEqual(status, "unavailable")

    async def test_bad_map_metadata_is_fallback_not_wrong_facilities(self):
        class Bad:
            async def capture(self, _): return NearbyMapResult("captured", b"bad-image", {})
        content, status = await NearbyReportGenerator(Bad(), ROOT / "fonts/NotoSansKR.ttf").generate(report())
        self.assertTrue(content.startswith(b"%PDF"))
        self.assertEqual(status, "unavailable")

    async def test_cancel_during_pdf_waits_for_computation_and_slot_cleanup(self):
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        class HeldRender(NearbyReportGenerator):
            def _render(self, value, result):
                started.set()
                release.wait(timeout=3)
                try: return super()._render(value, result)
                finally: finished.set()
        generator = HeldRender(KakaoReportCapture(enabled=False, origin="https://keco-safety-map.web.app"), ROOT / "fonts/NotoSansKR.ttf")
        task = asyncio.create_task(generator.generate(report()))
        self.assertTrue(await asyncio.to_thread(started.wait, 1))
        task.cancel()
        await asyncio.sleep(.02)
        self.assertFalse(task.done())
        release.set()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(finished.is_set())
        content, status = await generator.generate(report())
        self.assertTrue(content.startswith(b"%PDF"));self.assertEqual(status,"unavailable")

    async def test_cancel_while_waiting_for_pdf_does_not_render_cancelled_report(self):
        started, release = threading.Event(), threading.Event()
        rendered = []
        def render(_, value, *_args, **_kwargs):
            rendered.append(value.label)
            if value.label == "first":
                started.set()
                release.wait(timeout=3)
            return b"%PDF-unit"
        from dataclasses import replace
        generator = NearbyReportGenerator(KakaoReportCapture(enabled=False,
            origin="https://keco-safety-map.web.app"), ROOT / "fonts/NotoSansKR.ttf")
        with patch("safety_dashboard.api.nearby_reports.EnhancedNearbyPdfRenderer.render", render):
            first = asyncio.create_task(generator.generate(replace(report(), label="first")))
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            waiting = asyncio.create_task(generator.generate(replace(report(), label="cancelled")))
            try:
                await asyncio.sleep(.05)
                waiting.cancel()
                await asyncio.sleep(.05)
                cancelled_without_waiting_for_first = waiting.done()
            finally:
                release.set()
                await first
                await asyncio.gather(waiting, return_exceptions=True)
            self.assertTrue(cancelled_without_waiting_for_first)
            self.assertTrue(waiting.cancelled())
            self.assertEqual(rendered, ["first"])
            await generator.generate(replace(report(), label="after-cancel"))
            self.assertEqual(rendered, ["first", "after-cancel"])

    async def test_pdf_slot_wait_timeout_does_not_render_and_returns_request_slot(self):
        generator = NearbyReportGenerator(KakaoReportCapture(enabled=False,
            origin="https://keco-safety-map.web.app"), ROOT / "fonts/NotoSansKR.ttf")
        generator._pdf.acquire()
        timeout = asyncio.timeout
        try:
            with patch("safety_dashboard.api.nearby_reports.asyncio.timeout", lambda _: timeout(.03)), \
                 patch("safety_dashboard.api.nearby_reports.EnhancedNearbyPdfRenderer.render") as render:
                with self.assertRaises(NearbyReportBusy):
                    await generator.generate(report())
                render.assert_not_called()
        finally:
            generator._pdf.release()
        content, status = await generator.generate(report())
        self.assertTrue(content.startswith(b"%PDF"))
        self.assertEqual(status, "unavailable")


class ReportRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_post_contract_with_map_failure_and_no_monitoring(self):
        monitoring = Mock()
        monitoring.snapshot.side_effect = AssertionError("KMA must not be called")
        class Failed:
            async def capture(self, _): return NearbyMapResult("timeout")
        generator = NearbyReportGenerator(Failed(), ROOT / "fonts/NotoSansKR.ttf")
        app = create_app(service=monitoring, nearby_report_generator=generator)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/reports/nearby.pdf", json={"latitude": 35.8714, "longitude": 128.6014,
                "label": "검수 기준점", "radius_km": 5})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["X-Nearby-Map-Status"], "timeout")
            self.assertEqual(response.headers["X-Nearby-Facility-Count"], "3")
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertTrue(response.content.startswith(b"%PDF"))
            self.assertEqual((await client.get("/api/v1/health")).status_code, 200)
        monitoring.snapshot.assert_not_called()

    async def test_saturated_generation_is_429_and_does_not_block_health(self):
        class Busy:
            async def generate(self, _): raise NearbyReportBusy()
        app = create_app(nearby_report_generator=Busy())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/reports/nearby.pdf", json={"latitude": 35, "longitude": 129, "label": "검수", "radius_km": 5})
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.headers["Retry-After"], "3")
            self.assertEqual((await client.get("/api/v1/health")).status_code, 200)

    async def test_captured_pdf_and_identity_contract(self):
        image = io.BytesIO()
        Image.new("RGB", (1200, 620), "white").save(image, format="PNG")
        png = image.getvalue()  # 단위 테스트 이미지. 실제 SDK 증빙으로 사용하지 않는다.
        class Captured:
            async def capture(self, value):
                data = capture_input(value, "unit")
                data["geometry"] = {"groups": [{"number": 1, "ids": [r.facility.id for r in value.facilities]}]}
                data["pngSha256"] = hashlib.sha256(png).hexdigest()
                return NearbyMapResult("captured", png, data)
        app = create_app(nearby_report_generator=NearbyReportGenerator(Captured(), ROOT / "fonts/NotoSansKR.ttf"))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/reports/nearby.pdf", json={"latitude":35.8714,"longitude":128.6014,"label":"검수","radius_km":5})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["X-Nearby-Map-Status"], "captured")
            self.assertEqual(response.headers["X-Nearby-Facility-Count"], "3")

    async def test_request_deadline_and_disconnect_cancel_generation(self):
        class Slow:
            def __init__(self): self.cleaned = False
            async def generate(self, _):
                try: await asyncio.Event().wait()
                finally: self.cleaned = True
        for disconnect in (False, True):
            slow = Slow()
            app = create_app(nearby_report_generator=slow)
            timeout = asyncio.timeout
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                async def receive():
                    if disconnect: return {"type":"http.disconnect"}
                    await asyncio.Event().wait()
                with patch("safety_dashboard.api.routes.reports.asyncio.timeout", lambda _: timeout(.03)), \
                     patch("starlette.requests.Request.receive", property(lambda _: receive)):
                    response = await client.post("/api/v1/reports/nearby.pdf", json={"latitude":35,"longitude":129,"label":"검수","radius_km":5})
                self.assertEqual(response.status_code, 499 if disconnect else 504)
                self.assertTrue(slow.cleaned)
