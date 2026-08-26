"""공통 관제 snapshot의 영속화 경계."""

from __future__ import annotations

from typing import Protocol

from safety_dashboard.monitoring.snapshot import MonitoringSnapshot


class MonitoringSnapshotStore(Protocol):
    def save_latest(self, snapshot: MonitoringSnapshot) -> None: ...

    def load_latest(self) -> MonitoringSnapshot | None: ...
