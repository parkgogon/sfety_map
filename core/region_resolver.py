"""기상특보 구역과 시설 주소/지도 경계를 연결하는 규칙 (구버전 호환성 facade)."""

from __future__ import annotations

from safety_dashboard.domain.region_resolver import (
    KMA_WARNING_SCOPE_PREFIXES,
    WarningZoneIndex,
    _ADMIN_SUFFIX,
    _AMBIGUOUS_DISTRICTS,
    _DAEGU_BOUNDARIES,
    _base_admin_name,
    _compact,
    _feature_region_code,
    _parent_keywords,
    _polygonal_geometry,
    boundary_names_for_warning,
    dominant_warning,
    facility_matches_warning,
    normalize_warning_zone_data,
    warning_level_rank,
    warning_matches_facility,
)

__all__ = [
    "KMA_WARNING_SCOPE_PREFIXES",
    "WarningZoneIndex",
    "boundary_names_for_warning",
    "dominant_warning",
    "facility_matches_warning",
    "normalize_warning_zone_data",
    "warning_level_rank",
    "warning_matches_facility",
]
