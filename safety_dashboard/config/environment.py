"""API·Worker·관리자 인증이 공유하는 환경변수 접근."""

import os


def env_text(name: str) -> str:
    return os.getenv(name, "").strip()
