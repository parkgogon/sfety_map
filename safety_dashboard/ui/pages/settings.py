"""현재 브라우저 세션의 위험도 기준 설정 페이지."""

from __future__ import annotations

import html

import streamlit as st

from safety_dashboard.ui.admin_gate import require_admin_access
from safety_dashboard.ui.app_context import monitoring_context
from safety_dashboard.ui.policy_editor import render_policy_editor


require_admin_access()


try:
    context = monitoring_context(False)
except Exception as exc:
    st.error(f"위험도 기준을 구성할 수 없습니다: {exc}")
    st.stop()

st.markdown(
    '<div class="app-kicker">K-ECO SAFETY MONITORING</div>',
    unsafe_allow_html=True,
)
st.markdown('<div class="app-title">설정</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="app-subtitle">현재 브라우저에서 사용할 위험도 기준을 확인하고 편집합니다.</div>',
    unsafe_allow_html=True,
)

if context.temporary_policy:
    st.warning(
        "임시 위험도 기준 적용 중 · 이 브라우저 세션의 현장 지도, "
        "중앙 관제, Telegram과 PDF에만 반영됩니다."
    )
else:
    st.info("기본 위험도 기준을 사용 중입니다.")

st.markdown(
    '<div class="settings-policy-summary">'
    f'<b>기본 버전</b> · {html.escape(context.base_policy.version)}<br>'
    f'<b>현재 버전</b> · {html.escape(context.policy.version)}'
    '</div>',
    unsafe_allow_html=True,
)
st.markdown("### 특보 종류별 등급")
render_policy_editor(
    context.base_policy,
    context.policy,
    context.snapshot.warning_feed.warnings,
)

st.caption(
    "설정값은 파일·DB·다른 사용자에게 저장되지 않습니다. "
    "API 키와 시설 정보는 이 화면에서 변경할 수 없습니다."
)
