"""요청 메모리 안에서만 유지하는 지도 캡처 결과."""
from dataclasses import dataclass
from typing import Literal, Protocol

from safety_dashboard.application.nearby_report import NearbyReport

MapStatus = Literal["captured", "unavailable", "busy", "timeout"]


@dataclass(frozen=True)
class NearbyMapResult:
    status: MapStatus
    png: bytes | None = None
    metadata: dict | None = None


class NearbyMapCapture(Protocol):
    async def capture(self, report: NearbyReport) -> NearbyMapResult: ...
