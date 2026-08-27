"""HMAC-SHA256 기반 서명 및 만료 시간이 포함된 관리자 세션 토큰 매니저."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Callable


class AdminSessionError(ValueError):
    """세션 토큰의 형식이 잘못되었거나 변조된 경우."""


class AdminSessionExpiredError(AdminSessionError):
    """세션 유효 시간이 만료된 경우."""


@dataclass(frozen=True)
class AdminSession:
    created_at: int
    expires_at: int


class AdminSessionManager:
    """서버 비밀키로 서명된 세션 토큰을 발급하고 검증합니다."""

    COOKIE_NAME = "keco_admin_session"

    def __init__(
        self,
        secret_key: str,
        default_lifetime_seconds: int = 8 * 60 * 60,
        *,
        time_fn: Callable[[], float] = time.time,
    ) -> None:
        if not secret_key:
            secret_key = "keco-default-session-secret-key"
        self._secret = secret_key.encode("utf-8")
        self._default_lifetime = default_lifetime_seconds
        self._time_fn = time_fn

    def create_token(self, lifetime_seconds: int | None = None) -> str:
        """현재 시각 기준으로 서명된 세션 토큰 문자열을 반환합니다."""
        now = int(self._time_fn())
        lifetime = lifetime_seconds if lifetime_seconds is not None else self._default_lifetime
        expires_at = now + lifetime
        payload = f"{now}:{expires_at}"
        signature = hmac.new(
            self._secret,
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        raw_token = f"{payload}:{signature}"
        return base64.urlsafe_b64encode(raw_token.encode("utf-8")).decode("ascii")

    def verify_token(self, token: str) -> AdminSession:
        """토큰 서명과 만료 시간을 검증하고 세션 정보를 반환합니다."""
        if not token or not isinstance(token, str) or not token.strip():
            raise AdminSessionError("세션 토큰이 비어 있습니다.")

        token = token.strip()
        try:
            standard_b64 = token.replace("-", "+").replace("_", "/")
            decoded_bytes = base64.b64decode(standard_b64, validate=True)
            decoded = decoded_bytes.decode("utf-8")
            parts = decoded.split(":")
            if len(parts) != 3:
                raise AdminSessionError("세션 토큰 구조가 올바르지 않습니다.")
            created_str, expires_str, signature = parts
            created_at = int(created_str)
            expires_at = int(expires_str)
        except Exception as exc:
            raise AdminSessionError("세션 토큰 디코딩에 실패했습니다.") from exc


        payload = f"{created_at}:{expires_at}"
        expected_signature = hmac.new(
            self._secret,
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(signature, expected_signature):
            raise AdminSessionError("세션 서명이 일치하지 않습니다.")

        now = int(self._time_fn())
        if now >= expires_at:
            raise AdminSessionExpiredError("세션이 만료되었습니다.")

        return AdminSession(created_at=created_at, expires_at=expires_at)
