"""공식 KMA 특보구역 도형과 시설 좌표를 연결합니다."""

from __future__ import annotations

from core.region_resolver import WarningZoneIndex, warning_matches_facility
from safety_dashboard.domain.models import Facility, Warning


class OfficialZoneMatcher:
    def __init__(self, zone_index: WarningZoneIndex) -> None:
        self.zone_index = zone_index

    def matches(self, facility: Facility, warning: Warning) -> bool:
        return warning_matches_facility(
            {
                "latitude": facility.location.latitude,
                "longitude": facility.location.longitude,
                "address": facility.address,
            },
            {
                "region_code": warning.region_code,
                "region": warning.region,
                "region_up": warning.region_up,
            },
            self.zone_index,
        )
