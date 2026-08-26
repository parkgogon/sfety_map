"""여러 실행 화면이 함께 읽을 수 있는 버전 고정 관제 snapshot."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from safety_dashboard.application.contacts import public_contact
from safety_dashboard.domain.enums import DataHealth, RiskGrade, WarningLevel
from safety_dashboard.domain.models import (
    DashboardSnapshot,
    DashboardSummary,
    Facility,
    GeoPoint,
    RiskAssessment,
    RiskReason,
    Warning,
    WarningFeed,
)


MONITORING_SNAPSHOT_SCHEMA_VERSION = 1
UTC = dt.timezone.utc


class MonitoringSnapshotError(ValueError):
    """저장 snapshot의 계약이나 데이터 일관성이 올바르지 않음."""


@dataclass(frozen=True)
class MonitoringSnapshot:
    """정상 KMA 관제 회차와 그 출처를 함께 보존한다."""

    id: str
    schema_version: int
    stored_at: dt.datetime
    generated_at: dt.datetime
    kma_fetched_at: dt.datetime
    policy_version: str
    health: DataHealth
    dashboard: DashboardSnapshot

    @classmethod
    def capture(
        cls,
        dashboard: DashboardSnapshot,
        *,
        stored_at: dt.datetime | None = None,
    ) -> "MonitoringSnapshot":
        _validate_dashboard(dashboard)
        if dashboard.warning_feed.health is not DataHealth.LIVE:
            raise MonitoringSnapshotError(
                "정상 KMA 관제 결과만 공통 snapshot으로 저장할 수 있습니다."
            )
        captured_at = _aware(stored_at or dt.datetime.now(UTC))
        document = _dashboard_to_dict(dashboard)
        fingerprint = hashlib.sha256(
            json.dumps(
                document,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:16]
        generated_utc = _aware(dashboard.generated_at).astimezone(UTC)
        snapshot_id = f"ms-{generated_utc:%Y%m%dT%H%M%S%fZ}-{fingerprint}"
        return cls(
            id=snapshot_id,
            schema_version=MONITORING_SNAPSHOT_SCHEMA_VERSION,
            stored_at=captured_at,
            generated_at=_aware(dashboard.generated_at),
            kma_fetched_at=_aware(dashboard.warning_feed.fetched_at),
            policy_version=dashboard.policy_version,
            health=dashboard.warning_feed.health,
            dashboard=dashboard,
        )

    def to_document(self) -> dict[str, Any]:
        if self.schema_version != MONITORING_SNAPSHOT_SCHEMA_VERSION:
            raise MonitoringSnapshotError(
                f"지원하지 않는 snapshot 버전입니다: {self.schema_version}"
            )
        return {
            "snapshot_id": self.id,
            "schema_version": self.schema_version,
            "stored_at": _iso(self.stored_at),
            "generated_at": _iso(self.generated_at),
            "kma_fetched_at": _iso(self.kma_fetched_at),
            "policy_version": self.policy_version,
            "health": self.health.value,
            "dashboard": _dashboard_to_dict(self.dashboard),
        }

    @classmethod
    def from_document(cls, values: Mapping[str, Any]) -> "MonitoringSnapshot":
        try:
            schema_version = int(values["schema_version"])
            if schema_version != MONITORING_SNAPSHOT_SCHEMA_VERSION:
                raise MonitoringSnapshotError(
                    f"지원하지 않는 snapshot 버전입니다: {schema_version}"
                )
            dashboard = _dashboard_from_dict(_mapping(values["dashboard"]))
            result = cls(
                id=str(values["snapshot_id"]),
                schema_version=schema_version,
                stored_at=_datetime(values["stored_at"]),
                generated_at=_datetime(values["generated_at"]),
                kma_fetched_at=_datetime(values["kma_fetched_at"]),
                policy_version=str(values["policy_version"]),
                health=DataHealth(str(values["health"])),
                dashboard=dashboard,
            )
        except MonitoringSnapshotError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise MonitoringSnapshotError("저장된 관제 snapshot 형식이 잘못되었습니다.") from exc
        if result.health is not DataHealth.LIVE:
            raise MonitoringSnapshotError("저장된 관제 snapshot이 정상 상태가 아닙니다.")
        if result.health is not dashboard.warning_feed.health:
            raise MonitoringSnapshotError("snapshot 자료 상태가 서로 일치하지 않습니다.")
        if result.policy_version != dashboard.policy_version:
            raise MonitoringSnapshotError("snapshot 정책 버전이 서로 일치하지 않습니다.")
        if result.generated_at != _aware(dashboard.generated_at):
            raise MonitoringSnapshotError("snapshot 생성 시각이 서로 일치하지 않습니다.")
        if result.kma_fetched_at != _aware(dashboard.warning_feed.fetched_at):
            raise MonitoringSnapshotError("snapshot KMA 조회 시각이 서로 일치하지 않습니다.")
        _validate_dashboard(dashboard)
        expected_id = cls.capture(dashboard, stored_at=result.stored_at).id
        if not result.id or result.id != expected_id:
            raise MonitoringSnapshotError("snapshot ID와 저장 내용이 일치하지 않습니다.")
        return result


def _dashboard_to_dict(snapshot: DashboardSnapshot) -> dict[str, Any]:
    facilities = [_facility_to_dict(item) for item in snapshot.facilities]
    return {
        "generated_at": _iso(snapshot.generated_at),
        "warning_feed": {
            "warnings": [_warning_to_dict(item) for item in snapshot.warning_feed.warnings],
            "health": snapshot.warning_feed.health.value,
            "fetched_at": _iso(snapshot.warning_feed.fetched_at),
            "message": snapshot.warning_feed.message,
        },
        "facilities": facilities,
        "assessments": [_assessment_to_dict(item) for item in snapshot.assessments],
        "summary": {
            "active_warning_count": snapshot.summary.active_warning_count,
            "affected_facility_count": snapshot.summary.affected_facility_count,
            "high_risk_count": snapshot.summary.high_risk_count,
            "unassessed_count": snapshot.summary.unassessed_count,
            "highest_warning_level": snapshot.summary.highest_warning_level.value,
        },
        "policy_version": snapshot.policy_version,
        "notices": list(snapshot.notices),
    }


def _dashboard_from_dict(values: Mapping[str, Any]) -> DashboardSnapshot:
    facilities = tuple(
        _facility_from_dict(_mapping(item)) for item in values.get("facilities", [])
    )
    facility_by_id = {item.id: item for item in facilities}
    feed_values = _mapping(values["warning_feed"])
    summary_values = _mapping(values["summary"])
    snapshot = DashboardSnapshot(
        generated_at=_datetime(values["generated_at"]),
        warning_feed=WarningFeed(
            warnings=tuple(
                _warning_from_dict(_mapping(item))
                for item in feed_values.get("warnings", [])
            ),
            health=DataHealth(str(feed_values["health"])),
            fetched_at=_datetime(feed_values["fetched_at"]),
            message=str(feed_values.get("message", "")),
        ),
        facilities=facilities,
        assessments=tuple(
            _assessment_from_dict(_mapping(item), facility_by_id)
            for item in values.get("assessments", [])
        ),
        summary=DashboardSummary(
            active_warning_count=int(summary_values["active_warning_count"]),
            affected_facility_count=int(summary_values["affected_facility_count"]),
            high_risk_count=int(summary_values["high_risk_count"]),
            unassessed_count=int(summary_values["unassessed_count"]),
            highest_warning_level=WarningLevel(
                str(summary_values["highest_warning_level"])
            ),
        ),
        policy_version=str(values["policy_version"]),
        notices=tuple(str(item) for item in values.get("notices", [])),
    )
    return snapshot


def _facility_to_dict(facility: Facility) -> dict[str, Any]:
    return {
        "id": facility.id,
        "name": facility.name,
        "facility_type": facility.facility_type,
        "latitude": facility.location.latitude,
        "longitude": facility.location.longitude,
        "address": facility.address,
        "public_contact": public_contact(facility),
        "region_code": facility.region_code,
        "is_monitored": facility.is_monitored,
    }


def _facility_from_dict(values: Mapping[str, Any]) -> Facility:
    return Facility(
        id=str(values["id"]),
        name=str(values["name"]),
        facility_type=str(values["facility_type"]),
        location=GeoPoint(float(values["latitude"]), float(values["longitude"])),
        address=str(values["address"]),
        department=str(values.get("public_contact", "-")),
        manager="-",
        region_code=str(values.get("region_code", "")),
        is_monitored=bool(values.get("is_monitored", True)),
    )


def _warning_to_dict(warning: Warning) -> dict[str, Any]:
    return {
        "id": warning.id,
        "source": warning.source,
        "region_up_code": warning.region_up_code,
        "region_code": warning.region_code,
        "region_up": warning.region_up,
        "region": warning.region,
        "warning_type": warning.warning_type,
        "raw_level": warning.raw_level,
        "level": warning.level.value,
        "command": warning.command,
        "issued_at": _iso(warning.issued_at),
        "effective_at": _iso(warning.effective_at),
    }


def _warning_from_dict(values: Mapping[str, Any]) -> Warning:
    return Warning(
        id=str(values["id"]),
        source=str(values["source"]),
        region_up_code=str(values["region_up_code"]),
        region_code=str(values["region_code"]),
        region_up=str(values["region_up"]),
        region=str(values["region"]),
        warning_type=str(values["warning_type"]),
        raw_level=str(values["raw_level"]),
        level=WarningLevel(str(values["level"])),
        command=str(values.get("command", "")),
        issued_at=_optional_datetime(values.get("issued_at")),
        effective_at=_optional_datetime(values.get("effective_at")),
    )


def _assessment_to_dict(assessment: RiskAssessment) -> dict[str, Any]:
    return {
        "facility_id": assessment.facility.id,
        "grade": assessment.grade.value,
        "reasons": [
            {
                "warning_id": item.warning_id,
                "warning_type": item.warning_type,
                "raw_level": item.raw_level,
                "grade": item.grade.value,
                "region": item.region,
                "policy_key": item.policy_key,
            }
            for item in assessment.reasons
        ],
        "policy_version": assessment.policy_version,
        "assessed_at": _iso(assessment.assessed_at),
    }


def _assessment_from_dict(
    values: Mapping[str, Any],
    facility_by_id: Mapping[str, Facility],
) -> RiskAssessment:
    facility_id = str(values["facility_id"])
    try:
        facility = facility_by_id[facility_id]
    except KeyError as exc:
        raise MonitoringSnapshotError(
            f"판정 결과의 시설을 찾을 수 없습니다: {facility_id}"
        ) from exc
    return RiskAssessment(
        facility=facility,
        grade=RiskGrade(str(values["grade"])),
        reasons=tuple(
            RiskReason(
                warning_id=str(item["warning_id"]),
                warning_type=str(item["warning_type"]),
                raw_level=str(item["raw_level"]),
                grade=RiskGrade(str(item["grade"])),
                region=str(item["region"]),
                policy_key=str(item["policy_key"]),
            )
            for raw in values.get("reasons", [])
            for item in (_mapping(raw),)
        ),
        policy_version=str(values["policy_version"]),
        assessed_at=_datetime(values["assessed_at"]),
    )


def _validate_dashboard(snapshot: DashboardSnapshot) -> None:
    facility_ids = [item.id for item in snapshot.facilities]
    assessment_ids = [item.facility.id for item in snapshot.assessments]
    if len(facility_ids) != len(set(facility_ids)):
        raise MonitoringSnapshotError("관제 snapshot의 시설 ID가 중복되었습니다.")
    if facility_ids != assessment_ids:
        raise MonitoringSnapshotError(
            "관제 snapshot의 시설과 위험도 판정 결과가 일치하지 않습니다."
        )
    if not snapshot.policy_version:
        raise MonitoringSnapshotError("관제 snapshot의 정책 버전이 비어 있습니다.")
    if any(
        item.policy_version != snapshot.policy_version
        for item in snapshot.assessments
    ):
        raise MonitoringSnapshotError("시설 판정 정책 버전이 서로 일치하지 않습니다.")
    if snapshot.summary.active_warning_count != len(snapshot.warning_feed.warnings):
        raise MonitoringSnapshotError("활성 특보 요약 수가 원본과 일치하지 않습니다.")
    affected = [
        item for item in snapshot.assessments if item.grade is not RiskGrade.NONE
    ]
    if snapshot.summary.affected_facility_count != len(affected):
        raise MonitoringSnapshotError("영향시설 요약 수가 원본과 일치하지 않습니다.")
    if snapshot.summary.high_risk_count != sum(
        item.grade is RiskGrade.HIGH for item in affected
    ):
        raise MonitoringSnapshotError("상 위험 요약 수가 원본과 일치하지 않습니다.")
    if snapshot.summary.unassessed_count != sum(
        item.grade is RiskGrade.UNASSESSED for item in affected
    ):
        raise MonitoringSnapshotError("미판정 요약 수가 원본과 일치하지 않습니다.")
    highest = max(
        (item.level for item in snapshot.warning_feed.warnings),
        key=_warning_level_rank,
        default=WarningLevel.UNKNOWN,
    )
    if snapshot.summary.highest_warning_level is not highest:
        raise MonitoringSnapshotError("최고 특보 단계가 원본과 일치하지 않습니다.")


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MonitoringSnapshotError("snapshot 객체 형식이 잘못되었습니다.")
    return value


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _iso(value: dt.datetime | None) -> str | None:
    return _aware(value).isoformat() if value is not None else None


def _datetime(value: object) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return _aware(value)
    if not isinstance(value, str) or not value:
        raise MonitoringSnapshotError("snapshot 시각 값이 잘못되었습니다.")
    return _aware(dt.datetime.fromisoformat(value.replace("Z", "+00:00")))


def _optional_datetime(value: object) -> dt.datetime | None:
    return None if value in {None, ""} else _datetime(value)


def _warning_level_rank(level: WarningLevel) -> int:
    return {
        WarningLevel.UNKNOWN: 0,
        WarningLevel.ADVISORY: 1,
        WarningLevel.WARNING: 2,
        WarningLevel.CRITICAL: 3,
    }[level]
