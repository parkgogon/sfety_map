"""선택한 ITS CCTV 영상을 큰 작업창에서 표시합니다."""

from __future__ import annotations

from urllib.parse import urlsplit

import streamlit as st

from safety_dashboard.adapters.cctv import OFFICIAL_MAP_URL, SOURCE_PAGE_URL
from safety_dashboard.domain.models import NearbyCctv


@st.dialog("CCTV 영상 확인", width="large")
def cctv_viewer_dialog(cctv: NearbyCctv) -> None:
    st.subheader(cctv.name)
    updated = (
        f" · 자료 시각 {cctv.updated_at:%m-%d %H:%M}"
        if cctv.updated_at
        else ""
    )
    st.caption(
        f"{cctv.road_type} · 선택 시설에서 직선거리 "
        f"{cctv.distance_km:.1f}km{updated}"
    )
    scheme = urlsplit(cctv.video_url).scheme.lower()
    if scheme == "http":
        st.warning(
            "제공기관이 HTTP 영상 주소를 반환했습니다. "
            "브라우저 보안 정책에 따라 내장 재생이 차단될 수 있습니다."
        )
    if "MP4" in cctv.video_format.upper():
        st.video(
            cctv.video_url,
            format="video/mp4",
            autoplay=False,
            width="stretch",
        )
    else:
        st.warning(
            f"반환된 영상 형식이 {cctv.video_format or '확인 불가'}이므로 "
            "내장 MP4 재생을 생략합니다."
        )
    st.link_button(
        "새 탭에서 영상 열기",
        cctv.video_url,
        icon=":material/open_in_new:",
        width="stretch",
    )
    st.link_button(
        "ITS 공식 교통지도에서 확인",
        OFFICIAL_MAP_URL,
        icon=":material/map:",
        width="stretch",
    )
    st.caption(
        "영상은 인근 도로 상황 참고정보이며 시설 현장 영상이 아닙니다. "
        "재생이 안 되면 외부 링크를 이용하세요."
    )
    st.markdown(f"[출처 · ITS 국가교통정보센터]({SOURCE_PAGE_URL})")
