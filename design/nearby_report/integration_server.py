"""로컬 전용 API/실제 SDK 검수 서버. 운영 이미지에는 포함되지 않는다."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import time
from urllib.parse import urlsplit

from fastapi.responses import JSONResponse
from safety_dashboard.api.app import create_app
from safety_dashboard.api.nearby_reports import NearbyReportGenerator
from safety_dashboard.api.settings import ROOT
from safety_dashboard.adapters.kakao_report_capture import KakaoReportCapture, SDK_HOSTS
from safety_dashboard.adapters.facility_csv import CsvFacilityRepository
from safety_dashboard.application.facility_groups import FacilityGroupCatalog
from safety_dashboard.application.nearby_map import NearbyMapResult

WEB = Path(os.environ.get("NEARBY_QA_WEB", str(ROOT / "field_web/dist")))
metrics = {"scope": "Local API container and real SDK/tiles; static page response overrides only. No production app/API requests.",
           "activeCaptures": 0, "maxActiveCaptures": 0, "captures": [], "responses": [], "failures": []}


class LocalCapture(KakaoReportCapture):
    mode = "capture"

    async def capture(self, report):
        if self.mode == "unavailable":
            return NearbyMapResult("unavailable")
        result = await super().capture(report)
        metrics["captures"].append({"status": result.status})
        return result

    async def _capture(self, report):
        metrics["activeCaptures"] += 1
        metrics["maxActiveCaptures"] = max(metrics["maxActiveCaptures"], metrics["activeCaptures"])
        started = time.monotonic()
        try:
            return await super()._capture(report)
        finally:
            metrics["activeCaptures"] -= 1
            metrics["lastCaptureMs"] = round((time.monotonic() - started) * 1000)

    async def _prepare_page(self, page):
        async def asset(route):
            request = route.request
            parsed = urlsplit(request.url)
            relative = parsed.path.lstrip("/")
            target = (WEB / relative).resolve()
            if request.method != "GET" or not target.is_relative_to(WEB.resolve()) or not target.is_file() or not (relative == "report-map.html" or relative.startswith("assets/")):
                return await route.abort()
            extension = target.suffix
            content_type = {".html":"text/html", ".js":"application/javascript", ".css":"text/css", ".ttf":"font/ttf"}.get(extension, "application/octet-stream")
            await route.fulfill(status=200, content_type=content_type, body=target.read_bytes())
        await page.route(self.origin + "/**", asset)
        if self.mode == "blocked":
            await page.route("https://mts.kakaocdn.net/**", lambda route: route.abort())
        def response(res):
            parsed = urlsplit(res.url)
            if parsed.hostname in SDK_HOSTS:
                metrics["responses"].append({"host": parsed.hostname, "path": parsed.path, "status": res.status})
        def failure(req):
            parsed = urlsplit(req.url)
            metrics["failures"].append({"host": parsed.hostname, "path": parsed.path,
                                        "error": (req.failure or "unknown").split(" at ")[0], "qaMode": self.mode})
        page.on("response", response)
        page.on("requestfailed", failure)
        await super()._prepare_page(page)


def monitoring_fixture():
    facilities = CsvFacilityRepository(ROOT / "facilities_info.csv").list_monitored()
    catalog = FacilityGroupCatalog.load(ROOT / "safety_dashboard/config/facility_groups.toml")
    rows = []
    for f in facilities:
        group = catalog.group_for_type(f.facility_type)
        rows.append(dict(id=f.id,name=f.name,type=f.facility_type,group_id=group.id,group_label=group.label,
            latitude=f.location.latitude,longitude=f.location.longitude,address=f.address,public_contact="",
            grade="NONE",grade_label="영향 없음",grade_color="#176B87",meaning="검수용 고정 자료",
            recommended_action="검수용 고정 자료",reasons=[]))
    return dict(api_version="v1", generated_at="2026-10-25T09:00:00+09:00",
        status=dict(health="SIMULATION",fetched_at="2026-10-25T09:00:00+09:00",detail="연결 검수용 고정 자료",zone_health="LIVE",zone_detail="고정 자료"),
        policy=dict(version="integration-qa",temporary=False),
        summary=dict(active_warning_count=0,affected_facility_count=0,high_risk_count=0,unassessed_count=0,highest_warning_level=""),
        groups=[dict(id=g.id,label=g.label,count=sum(f["group_id"]==g.id for f in rows)) for g in catalog.groups],
        warnings=[], warning_zones=dict(type="FeatureCollection",features=[]), facilities=rows, notices=[])


class FixedMonitoring:
    def snapshot(self, **_): raise AssertionError("QA must not query KMA/snapshot")
    def monitoring(self, **_): return monitoring_fixture()


capture = LocalCapture(enabled=True, origin="https://keco-safety-map.web.app")
app = create_app(service=FixedMonitoring(), nearby_report_generator=NearbyReportGenerator(capture, ROOT / "fonts/NotoSansKR.ttf"))


@app.middleware("http")
async def local_only(request, call_next):
    path = request.url.path
    if path == "/__qa/status" and request.method == "GET":
        result = dict(metrics)
        try:
            result["cgroupMemoryBytes"] = int(Path("/sys/fs/cgroup/memory.current").read_text())
        except OSError:
            result["cgroupMemoryBytes"] = None
        return JSONResponse(result)
    if path == "/__qa/mode" and request.method == "POST":
        mode = (await request.json()).get("mode")
        if mode not in ("capture", "unavailable", "blocked"):
            return JSONResponse({"error":"invalid QA mode"}, status_code=400)
        capture.mode = mode
        return JSONResponse({"mode":mode})
    if path == "/internal/v1/admin/session" and request.method == "GET":
        return JSONResponse({"authenticated": False})
    if (request.method == "POST" and path == "/api/v1/reports/nearby.pdf") or (request.method == "GET" and path in ("/api/v1/monitoring", "/api/v1/health")):
        return await call_next(request)
    return JSONResponse({"detail":"Local QA does not provide this route"}, status_code=503)
