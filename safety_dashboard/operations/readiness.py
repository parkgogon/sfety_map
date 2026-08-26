"""외부 가동상태 감시에 사용할 최소 운영 준비 상태."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping
from dataclasses import dataclass


StatusProvider = Callable[[], Mapping[str, object]]


@dataclass(frozen=True)
class OperationalReadiness:
    checked_at: dt.datetime
    healthy: bool
    worker_status: str
    last_run_at: dt.datetime | None
    worker_age_seconds: int | None
    max_worker_age_seconds: int
    automation_mode: str
    kma_status: str
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "status": "ok" if self.healthy else "degraded",
            "checked_at": self.checked_at.isoformat(),
            "worker": {
                "status": self.worker_status,
                "last_run_at": (
                    self.last_run_at.isoformat() if self.last_run_at else None
                ),
                "age_seconds": self.worker_age_seconds,
                "max_age_seconds": self.max_worker_age_seconds,
            },
            "automation": {"mode": self.automation_mode},
            "kma": {"status": self.kma_status},
            "reason": self.reason,
        }


class OperationalReadinessService:
    """비공개 자동 관제의 최근 실행 시각을 외부 감시용으로 판정한다."""

    def __init__(
        self,
        status_provider: StatusProvider,
        *,
        max_worker_age: dt.timedelta = dt.timedelta(minutes=10),
        expected_mode: str = "live",
    ) -> None:
        if max_worker_age <= dt.timedelta(0):
            raise ValueError("자동 관제 지연 기준은 0초보다 커야 합니다.")
        self.status_provider = status_provider
        self.max_worker_age = max_worker_age
        self.expected_mode = expected_mode

    def check(self, now: dt.datetime | None = None) -> OperationalReadiness:
        checked_at = _aware(now or dt.datetime.now(dt.timezone.utc))
        max_age_seconds = int(self.max_worker_age.total_seconds())
        try:
            status = dict(self.status_provider())
        except Exception:
            return OperationalReadiness(
                checked_at=checked_at,
                healthy=False,
                worker_status="unavailable",
                last_run_at=None,
                worker_age_seconds=None,
                max_worker_age_seconds=max_age_seconds,
                automation_mode="unknown",
                kma_status="unknown",
                reason="status_store_unavailable",
            )

        mode = str(status.get("mode", "unknown")).strip().lower() or "unknown"
        kma_status = (
            str(status.get("kma_health", "unknown")).strip().lower()
            or "unknown"
        )
        last_run_at = _optional_datetime(status.get("last_run_at"))
        if last_run_at is None:
            return OperationalReadiness(
                checked_at=checked_at,
                healthy=False,
                worker_status="unknown",
                last_run_at=None,
                worker_age_seconds=None,
                max_worker_age_seconds=max_age_seconds,
                automation_mode=mode,
                kma_status=kma_status,
                reason="worker_has_not_run",
            )

        age_seconds = max(
            0,
            int((checked_at - last_run_at.astimezone(dt.timezone.utc)).total_seconds()),
        )
        worker_fresh = age_seconds <= max_age_seconds
        mode_live = mode == self.expected_mode
        if not mode_live:
            reason = "automation_not_live"
        elif not worker_fresh:
            reason = "worker_stale"
        else:
            reason = "ready"
        return OperationalReadiness(
            checked_at=checked_at,
            healthy=worker_fresh and mode_live,
            worker_status="ok" if worker_fresh else "stale",
            last_run_at=last_run_at,
            worker_age_seconds=age_seconds,
            max_worker_age_seconds=max_age_seconds,
            automation_mode=mode,
            kma_status=kma_status,
            reason=reason,
        )


def _optional_datetime(value: object) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return _aware(value)
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return _aware(parsed)


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
