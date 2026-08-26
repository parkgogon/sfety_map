"""Streamlit이 Cloud Run의 공통 관제 snapshot을 읽는 HTTP 어댑터."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import requests

from safety_dashboard.domain.models import DashboardSnapshot
from safety_dashboard.monitoring.snapshot import (
    MONITORING_SNAPSHOT_SCHEMA_VERSION,
    MonitoringSnapshotError,
    dashboard_snapshot_from_document,
)


class MonitoringSnapshotApiError(RuntimeError):
    """공통 관제 snapshot API를 안전하게 사용할 수 없음."""


class MonitoringSnapshotApiClient:
    def __init__(
        self,
        base_url: str,
        admin_token: str,
        *,
        timeout: float = 12,
        get: Callable[..., Any] = requests.get,
    ) -> None:
        self.base_url = base_url.strip().rstrip("/")
        self.admin_token = admin_token.strip()
        self.timeout = timeout
        self._get = get

    def fetch(self) -> DashboardSnapshot:
        if not self._configured():
            raise MonitoringSnapshotApiError(
                "공통 관제 API 주소 또는 관리자 토큰이 설정되지 않았습니다."
            )
        try:
            response = self._get(
                self.base_url + "/internal/v1/monitoring/snapshot",
                headers={"X-Alert-Admin-Token": self.admin_token},
                params={"mode": "live"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise MonitoringSnapshotError("API 응답이 객체가 아닙니다.")
            if payload.get("api_version") != "v1":
                raise MonitoringSnapshotError("API 버전이 일치하지 않습니다.")
            if (
                payload.get("snapshot_schema_version")
                != MONITORING_SNAPSHOT_SCHEMA_VERSION
            ):
                raise MonitoringSnapshotError(
                    "관제 snapshot 버전이 일치하지 않습니다."
                )
            values = payload.get("snapshot")
            if not isinstance(values, dict):
                raise MonitoringSnapshotError(
                    "관제 snapshot 본문이 올바르지 않습니다."
                )
            return dashboard_snapshot_from_document(values)
        except MonitoringSnapshotApiError:
            raise
        except Exception as exc:
            raise MonitoringSnapshotApiError(
                "공통 관제 snapshot을 불러오지 못했습니다."
            ) from exc

    def _configured(self) -> bool:
        parsed = urlsplit(self.base_url)
        return (
            parsed.scheme in {"http", "https"}
            and bool(parsed.netloc)
            and bool(self.admin_token)
        )
