"""시설 조회·지도 캡처·PDF의 제한된 요청 단위 조립."""
from __future__ import annotations

import asyncio
import threading

from starlette.concurrency import run_in_threadpool

from safety_dashboard.adapters.enhanced_nearby_pdf import EnhancedNearbyPdfRenderer, validate_map
from safety_dashboard.application.nearby_map import NearbyMapCapture, NearbyMapResult
from safety_dashboard.application.nearby_report import NearbyReport


class NearbyReportBusy(Exception):
    pass


class NearbyReportGenerator:
    def __init__(self, capture: NearbyMapCapture, font_path):
        self.capture = capture
        self.font_path = font_path
        self._requests = threading.BoundedSemaphore(3)
        self._pdf = threading.BoundedSemaphore(1)

    async def generate(self, report: NearbyReport) -> tuple[bytes, str]:
        if not self._requests.acquire(blocking=False):
            raise NearbyReportBusy()
        # 생성 스레드가 시작된 뒤에는 스레드의 finally가 요청 슬롯도 반환한다.
        transferred = False
        pdf_reserved = False
        try:
            try:
                result = await self.capture.capture(report)
            except asyncio.CancelledError:
                raise
            except Exception:
                result = NearbyMapResult("unavailable")
            if result.status == "captured":
                try:
                    validate_map(report, result.metadata or {})
                    import hashlib
                    if not result.png or not result.png.startswith(b"\x89PNG\r\n\x1a\n") or hashlib.sha256(result.png).hexdigest() != (result.metadata or {}).get("pngSha256"):
                        raise ValueError("지도 이미지 불일치")
                except (KeyError, TypeError, ValueError):
                    result = NearbyMapResult("unavailable")
            try:
                # 계산 슬롯을 기다리는 동안에는 스레드를 시작하지 않는다.
                # 닫힌 요청은 즉시 취소하고, 이미 시작한 PDF 계산만 끝까지 정리한다.
                async with asyncio.timeout(10):
                    while not self._pdf.acquire(blocking=False):
                        await asyncio.sleep(.025)
                pdf_reserved = True
            except TimeoutError:
                raise NearbyReportBusy() from None
            task = asyncio.create_task(run_in_threadpool(self._render, report, result))
            transferred = True
            # 호출이 취소돼도 이미 실행 중인 PDF 스레드의 슬롯은 실제 종료 때까지 유지한다.
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                # Cloud Run 요청 CPU가 해제되기 전에 이미 시작한 계산과 슬롯 정리를 마친다.
                await asyncio.shield(asyncio.gather(task, return_exceptions=True))
                raise
        finally:
            if not transferred:
                if pdf_reserved:
                    self._pdf.release()
                self._requests.release()

    def _render(self, report, result):
        try:
            content = EnhancedNearbyPdfRenderer(self.font_path).render(report, result.png, result.metadata, map_status=result.status)
            return content, result.status
        finally:
            self._pdf.release()
            self._requests.release()
