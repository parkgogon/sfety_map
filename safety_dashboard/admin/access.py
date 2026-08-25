"""임시 Streamlit 관리자 잠금용 서버 검증 서비스."""

from __future__ import annotations

import hmac
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

from safety_dashboard.api.settings import _secret


class AdminAccessConfigurationError(RuntimeError):
    """관리자 비밀번호가 서버에 설정되지 않은 상태."""


class AdminAccessDeniedError(RuntimeError):
    """입력한 관리자 비밀번호가 올바르지 않은 상태."""


class AdminAccessThrottledError(RuntimeError):
    """짧은 시간에 인증 실패가 누적되어 잠시 차단된 상태."""


@dataclass(frozen=True)
class AdminAccessSettings:
    password: str = ""
    session_seconds: int = 8 * 60 * 60
    failure_limit: int = 5
    failure_window_seconds: int = 5 * 60

    @classmethod
    def from_environment(cls) -> "AdminAccessSettings":
        def integer(name: str, default: int, minimum: int) -> int:
            try:
                return max(minimum, int(os.getenv(name, str(default))))
            except ValueError:
                return default

        return cls(
            password=_secret(
                "ADMIN_ACCESS_PASSWORD",
                "admin",
                "access_password",
            ),
            session_seconds=integer(
                "ADMIN_SESSION_SECONDS",
                8 * 60 * 60,
                15 * 60,
            ),
            failure_limit=integer("ADMIN_LOGIN_FAILURE_LIMIT", 5, 3),
            failure_window_seconds=integer(
                "ADMIN_LOGIN_FAILURE_WINDOW_SECONDS",
                5 * 60,
                60,
            ),
        )


class AdminAccessVerifier:
    """비밀번호를 상수시간 비교하고 반복 실패를 프로세스 단위로 제한한다."""

    def __init__(
        self,
        settings: AdminAccessSettings,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self._monotonic = monotonic
        self._failures: deque[float] = deque()
        self._lock = threading.Lock()

    def verify(self, supplied_password: str) -> int:
        """성공하면 Streamlit 세션 유지시간(초)을 반환한다."""

        if not self.settings.password:
            raise AdminAccessConfigurationError("관리자 잠금이 설정되지 않음")

        with self._lock:
            now = self._monotonic()
            cutoff = now - self.settings.failure_window_seconds
            while self._failures and self._failures[0] <= cutoff:
                self._failures.popleft()
            if len(self._failures) >= self.settings.failure_limit:
                raise AdminAccessThrottledError("관리자 인증이 잠시 제한됨")
            if not hmac.compare_digest(
                supplied_password.encode("utf-8"),
                self.settings.password.encode("utf-8"),
            ):
                self._failures.append(now)
                raise AdminAccessDeniedError("관리자 인증 실패")
            self._failures.clear()
            return self.settings.session_seconds
