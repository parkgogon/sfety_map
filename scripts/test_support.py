"""자동 테스트에서 실제 HTTP 요청과 TCP 연결을 막는다. 운영 코드에는 사용하지 않는다."""

from contextlib import ExitStack
import socket
from unittest.mock import patch

import requests


class ExternalNetworkBlocked(AssertionError):
    pass


class NetworkGuard:
    def __init__(self):
        self.attempts = 0
        self._patches = ExitStack()

    def _block(self, *_args, **_kwargs):
        self.attempts += 1
        # 요청 URL에는 토큰이 들어갈 수 있으므로 목적지나 요청 내용을 출력하지 않는다.
        raise ExternalNetworkBlocked(
            "자동 테스트에서는 실제 외부 통신을 허용하지 않습니다."
        )

    def __enter__(self):
        original_connect = socket.socket.connect
        original_connect_ex = socket.socket.connect_ex

        def guarded_connect(connection, *args, **kwargs):
            if connection.family in (socket.AF_INET, socket.AF_INET6):
                return self._block()
            return original_connect(connection, *args, **kwargs)

        def guarded_connect_ex(connection, *args, **kwargs):
            if connection.family in (socket.AF_INET, socket.AF_INET6):
                return self._block()
            return original_connect_ex(connection, *args, **kwargs)

        self._patches.enter_context(patch.object(requests.Session, "send", self._block))
        self._patches.enter_context(
            patch.object(socket, "create_connection", self._block)
        )
        self._patches.enter_context(
            patch.object(socket.socket, "connect", guarded_connect)
        )
        self._patches.enter_context(
            patch.object(socket.socket, "connect_ex", guarded_connect_ex)
        )
        return self

    def assert_unused(self):
        if self.attempts:
            raise ExternalNetworkBlocked(
                f"가짜 제공자로 대체하지 않은 실제 통신 시도 {self.attempts}건을 차단했습니다."
            )

    def __exit__(self, *_exc):
        self._patches.close()
