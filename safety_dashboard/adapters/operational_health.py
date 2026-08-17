"""관리자 상태 보고에 필요한 공개 경로와 사용자 Telegram 읽기 점검."""

from __future__ import annotations

import datetime as dt
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from safety_dashboard.adapters.telegram import TelegramNotifier
from safety_dashboard.alerts.domain import HealthCheck, OperationalHealthReport


class HttpSystemHealthProbe:
    def __init__(
        self,
        dashboard_base_url: str,
        user_telegram: TelegramNotifier | None,
        timeout: float = 5,
    ) -> None:
        self.base_url = dashboard_base_url.rstrip("/")
        self.user_telegram = user_telegram
        self.timeout = timeout

    def check(self, now: dt.datetime) -> OperationalHealthReport:
        with ThreadPoolExecutor(max_workers=3) as executor:
            web = executor.submit(self._http_check, "사용자 웹", self.base_url + "/")
            api = executor.submit(
                self._http_check,
                "공개 API",
                self.base_url + "/api/v1/health",
            )
            telegram = executor.submit(self._telegram_check)
            checks = (web.result(), api.result(), telegram.result())
        return OperationalHealthReport(now, checks)

    def _http_check(self, name: str, url: str) -> HealthCheck:
        started = time.monotonic()
        try:
            response = requests.get(url, timeout=self.timeout)
            latency = round((time.monotonic() - started) * 1000)
            healthy = 200 <= response.status_code < 400
            return HealthCheck(
                name,
                healthy,
                f"HTTP {response.status_code}",
                latency,
            )
        except requests.RequestException as exc:
            latency = round((time.monotonic() - started) * 1000)
            return HealthCheck(
                name,
                False,
                f"{type(exc).__name__}",
                latency,
            )

    def _telegram_check(self) -> HealthCheck:
        if self.user_telegram is None:
            return HealthCheck("사용자 Telegram", False, "설정되지 않음")
        result = self.user_telegram.check_chat()
        return HealthCheck(
            "사용자 Telegram",
            result.success,
            result.title or result.message,
        )
