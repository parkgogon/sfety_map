"""Streamlit 중앙 관제와 설정 화면의 임시 관리자 잠금."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlsplit

import requests
import streamlit as st

from safety_dashboard.ui.app_context import secret


SESSION_EXPIRES_AT_KEY = "admin_access_expires_at"


def admin_session_is_active(
    state: dict[str, Any],
    *,
    now: float | None = None,
) -> bool:
    current = time.time() if now is None else now
    try:
        return float(state.get(SESSION_EXPIRES_AT_KEY, 0)) > current
    except (TypeError, ValueError):
        return False


def verify_admin_password(
    base_url: str,
    password: str,
    *,
    timeout: float = 7,
) -> tuple[bool, int, str]:
    """입력 비밀번호는 HTTPS 요청 본문으로만 전달하고 저장하지 않는다."""

    parts = urlsplit(base_url)
    local_development = parts.hostname in {"127.0.0.1", "localhost"}
    if (
        not parts.hostname
        or parts.username
        or parts.password
        or (parts.scheme != "https" and not local_development)
    ):
        return False, 0, "안전한 HTTPS 관리자 인증 주소가 필요합니다."
    try:
        response = requests.post(
            base_url.rstrip("/") + "/internal/v1/admin/access",
            json={"password": password},
            timeout=timeout,
            headers={"Accept": "application/json"},
        )
    except requests.RequestException:
        return False, 0, "인증 서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요."
    if response.status_code == 200:
        try:
            expires_in = int(response.json().get("expires_in", 0))
        except (TypeError, ValueError):
            return False, 0, "인증 서버 응답을 확인하지 못했습니다."
        if expires_in <= 0:
            return False, 0, "인증 서버 응답을 확인하지 못했습니다."
        return True, expires_in, ""
    if response.status_code == 429:
        return False, 0, "인증 실패가 반복되어 5분 후 다시 시도해 주세요."
    if response.status_code == 503:
        return False, 0, "관리자 잠금이 아직 서버에 설정되지 않았습니다."
    return False, 0, "비밀번호가 올바르지 않습니다."


def require_admin_access() -> None:
    """인증되지 않은 세션에서는 호출한 페이지의 실행을 즉시 중단한다."""

    if admin_session_is_active(st.session_state):
        with st.sidebar:
            st.caption("관리자 인증됨 · 브라우저 세션 종료 또는 잠금 시 해제")
            if st.button(
                "관리자 화면 잠금",
                icon=":material/lock:",
                width="stretch",
                key="admin-access-lock",
            ):
                st.session_state.pop(SESSION_EXPIRES_AT_KEY, None)
                st.rerun()
        return

    st.session_state.pop(SESSION_EXPIRES_AT_KEY, None)
    st.markdown(
        '<div class="app-kicker">K-ECO SAFETY MONITORING</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="app-title">관리자 확인</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="app-subtitle">중앙 관제와 설정은 관리자 비밀번호가 필요합니다.</div>',
        unsafe_allow_html=True,
    )

    base_url = (
        secret("admin", "api_url", "ADMIN_ACCESS_API_URL")
        or secret("alerting", "admin_api_url", "ALERT_ADMIN_API_URL")
    )
    if not base_url:
        st.error("관리자 인증 서버 주소가 설정되지 않았습니다.")
        st.stop()

    with st.form("admin-access-form", clear_on_submit=True):
        password = st.text_input(
            "관리자 비밀번호",
            type="password",
            autocomplete="current-password",
            placeholder="비밀번호 입력",
        )
        submitted = st.form_submit_button(
            "관리자 화면 열기",
            type="primary",
            width="stretch",
        )
    if submitted:
        if not password:
            st.error("비밀번호를 입력해 주세요.")
        else:
            with st.spinner("관리자 권한을 확인하고 있습니다..."):
                success, expires_in, detail = verify_admin_password(
                    base_url,
                    password,
                )
            if success:
                st.session_state[SESSION_EXPIRES_AT_KEY] = time.time() + expires_in
                st.rerun()
            st.error(detail)
    st.caption("비밀번호는 브라우저나 코드에 저장되지 않으며 HTTPS로 서버에서 확인합니다.")
    st.stop()
