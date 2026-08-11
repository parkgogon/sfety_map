"""역할별 화면을 연결하는 Streamlit Cloud 고정 진입점."""

from pathlib import Path

import streamlit as st


ROOT = Path(__file__).resolve().parent
STYLE_PATHS = (
    ROOT / "safety_dashboard/ui/design_tokens.css",
    ROOT / "safety_dashboard/ui/style.css",
)

st.set_page_config(
    page_title="기상재난 시설 관제",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.markdown(
    "<style>" + "\n".join(
        path.read_text(encoding="utf-8") for path in STYLE_PATHS
    ) + "</style>",
    unsafe_allow_html=True,
)

field_page = st.Page(
    "safety_dashboard/ui/pages/field_map.py",
    title="현장 지도",
    icon=":material/map:",
    url_path="field",
    default=True,
)
control_page = st.Page(
    "safety_dashboard/ui/pages/control.py",
    title="중앙 관제",
    icon=":material/campaign:",
    url_path="control",
)
settings_page = st.Page(
    "safety_dashboard/ui/pages/settings.py",
    title="설정",
    icon=":material/tune:",
    url_path="settings",
)

navigation = st.navigation(
    [field_page, control_page, settings_page],
    position="hidden",
)
with st.container(key="role-navigation"):
    navigation_columns = st.columns(3, gap="small")
    navigation_columns[0].page_link(
        field_page,
        label="현장 지도",
        icon=":material/map:",
        width="stretch",
    )
    navigation_columns[1].page_link(
        control_page,
        label="중앙 관제",
        icon=":material/campaign:",
        width="stretch",
    )
    navigation_columns[2].page_link(
        settings_page,
        label="설정",
        icon=":material/tune:",
        width="stretch",
    )
navigation.run()
