"""현재 브라우저에만 적용되는 위험도 기준 편집 작업창."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import pandas as pd
import streamlit as st

from safety_dashboard.application.risk_configuration import (
    editable_matrix,
    session_policy,
)
from safety_dashboard.domain.enums import RiskGrade, WarningLevel
from safety_dashboard.domain.models import Warning
from safety_dashboard.domain.risk_policy import RiskPolicy, RiskPolicyError
from safety_dashboard.ui.workflow import grade_label


SESSION_MATRIX_KEY = "temporary_risk_matrix"
SESSION_BASE_VERSION_KEY = "temporary_risk_base_version"

_GRADE_BY_LABEL = {grade_label(item): item for item in RiskGrade}


def effective_policy(base_policy: RiskPolicy) -> tuple[RiskPolicy, bool]:
    """session state가 유효할 때만 임시 정책을 복원합니다."""

    if st.session_state.get(SESSION_BASE_VERSION_KEY) != base_policy.version:
        st.session_state.pop(SESSION_MATRIX_KEY, None)
        st.session_state.pop(SESSION_BASE_VERSION_KEY, None)
        return base_policy, False
    values = st.session_state.get(SESSION_MATRIX_KEY)
    if not values:
        return base_policy, False
    try:
        return session_policy(base_policy, values), True
    except RiskPolicyError:
        st.session_state.pop(SESSION_MATRIX_KEY, None)
        st.session_state.pop(SESSION_BASE_VERSION_KEY, None)
        return base_policy, False


def _clear_outputs() -> None:
    st.session_state.pop("report_pdf", None)
    st.session_state.pop("report_name", None)
    st.session_state.pop("report_fingerprint", None)


@st.dialog("위험도 기준 설정", width="large")
def policy_editor_dialog(
    base_policy: RiskPolicy,
    current_policy: RiskPolicy,
    warnings: Sequence[Warning],
) -> None:
    active_types = {item.warning_type for item in warnings}
    unknown_active = tuple(
        item for item in active_types if item not in base_policy.warning_matrix
    )
    matrix = editable_matrix(current_policy, unknown_active)
    original_order = {name: index for index, name in enumerate(matrix)}
    warning_types = sorted(
        matrix,
        key=lambda name: (name not in active_types, original_order[name]),
    )

    st.caption(
        "현재 브라우저에만 적용됩니다. 셀을 모두 편집한 뒤 적용 버튼을 누르면 "
        "지도·지표·Telegram·PDF가 한 번에 다시 계산됩니다."
    )
    if active_types:
        st.info(
            f"현재 발효 특보 종류 {len(active_types)}개가 표 상단에 표시됩니다."
        )
    rows = pd.DataFrame(
        [
            {
                "상태": (
                    "🔴 발효 중 · 미등록"
                    if warning_type in unknown_active
                    else "🔴 발효 중"
                    if warning_type in active_types
                    else ""
                ),
                "특보": warning_type,
                "주의보": grade_label(
                    RiskGrade(matrix[warning_type][WarningLevel.ADVISORY.value])
                ),
                "경보": grade_label(
                    RiskGrade(matrix[warning_type][WarningLevel.WARNING.value])
                ),
                "중대": grade_label(
                    RiskGrade(matrix[warning_type][WarningLevel.CRITICAL.value])
                ),
            }
            for warning_type in warning_types
        ]
    )
    active_signature = hashlib.sha1(
        "|".join(sorted(active_types)).encode("utf-8")
    ).hexdigest()[:8]
    with st.form(
        f"risk-policy-form-{current_policy.version}-{active_signature}",
        border=False,
    ):
        edited = st.data_editor(
            rows,
            hide_index=True,
            width="stretch",
            height=520,
            disabled=("상태", "특보"),
            column_config={
                "상태": st.column_config.TextColumn("상태", width="medium"),
                "특보": st.column_config.TextColumn("특보", width="medium"),
                "주의보": st.column_config.SelectboxColumn(
                    "주의보",
                    options=list(_GRADE_BY_LABEL),
                    required=True,
                    width="small",
                ),
                "경보": st.column_config.SelectboxColumn(
                    "경보",
                    options=list(_GRADE_BY_LABEL),
                    required=True,
                    width="small",
                ),
                "중대": st.column_config.SelectboxColumn(
                    "중대",
                    options=list(_GRADE_BY_LABEL),
                    required=True,
                    width="small",
                ),
            },
            key=f"risk-policy-editor-{current_policy.version}-{active_signature}",
        )
        apply_column, reset_column = st.columns(2)
        apply_clicked = apply_column.form_submit_button(
            "현재 세션에 적용",
            type="primary",
            width="stretch",
        )
        reset_clicked = reset_column.form_submit_button(
            "기본 기준으로 되돌리기",
            width="stretch",
        )

    if apply_clicked:
        try:
            values = {
                str(row["특보"]): {
                    WarningLevel.ADVISORY.value: _GRADE_BY_LABEL[
                        str(row["주의보"])
                    ].value,
                    WarningLevel.WARNING.value: _GRADE_BY_LABEL[
                        str(row["경보"])
                    ].value,
                    WarningLevel.CRITICAL.value: _GRADE_BY_LABEL[
                        str(row["중대"])
                    ].value,
                }
                for row in edited.to_dict("records")
            }
            session_policy(base_policy, values)
        except (KeyError, TypeError, RiskPolicyError) as exc:
            st.error(f"위험도 기준을 적용할 수 없습니다: {exc}")
        else:
            st.session_state[SESSION_MATRIX_KEY] = values
            st.session_state[SESSION_BASE_VERSION_KEY] = base_policy.version
            _clear_outputs()
            st.rerun()

    if reset_clicked:
        st.session_state.pop(SESSION_MATRIX_KEY, None)
        st.session_state.pop(SESSION_BASE_VERSION_KEY, None)
        _clear_outputs()
        st.rerun()
