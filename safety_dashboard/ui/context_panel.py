"""선택 시설의 공식 재난문자와 외부 뉴스 링크를 표시합니다."""

from __future__ import annotations

import streamlit as st

from safety_dashboard.adapters.cctv import (
    OFFICIAL_MAP_URL,
    SOURCE_PAGE_URL as CCTV_SOURCE_URL,
)
from safety_dashboard.adapters.disaster_messages import SOURCE_PAGE_URL
from safety_dashboard.application.context_info import describe_cctv_timing
from safety_dashboard.domain.enums import ContextStatus
from safety_dashboard.domain.models import CctvFeed, DisasterMessageFeed, FacilityRegion


def render_facility_context(
    region: FacilityRegion | None,
    feed: DisasterMessageFeed | None,
    news_url: str,
    cctv_feed: CctvFeed | None = None,
) -> None:
    _render_cctv_status(cctv_feed)
    count = len(feed.messages) if feed else 0
    with st.expander(
        f"관련 재난문자 {count}건",
        expanded=bool(feed and feed.status is ContextStatus.LIVE and count),
    ):
        if region is None:
            st.info("시설 주소에서 시·도와 시·군·구를 확인할 수 없습니다.")
        elif feed is None or feed.status is ContextStatus.NOT_CONFIGURED:
            st.info(
                "행정안전부 재난문자 API 연동 준비 중입니다. "
                "API 키를 설정하면 자동으로 활성화됩니다."
            )
        elif feed.status is ContextStatus.ERROR:
            st.warning(feed.detail or "재난문자를 조회하지 못했습니다.")
            st.caption("기상청 관제·Telegram·PDF 기능은 계속 사용할 수 있습니다.")
        elif not feed.messages:
            st.info("최근 6시간 내 관련 재난문자가 없습니다.")
            st.caption("문자가 없다는 것은 현장이 안전하다는 판정이 아닙니다.")
        else:
            st.caption(
                f"{region.province} · {region.district} · "
                f"최근 6시간 · {feed.fetched_at:%H:%M} 조회"
            )
            for message in feed.messages:
                with st.container(border=True):
                    st.caption(
                        f"{message.created_at:%m-%d %H:%M} · "
                        f"{message.emergency_step} · {message.disaster_type}"
                    )
                    st.write(message.content)
                    st.caption("수신지역 · " + " · ".join(message.regions))
        st.markdown(f"[출처 · 행정안전부 재난안전데이터]({SOURCE_PAGE_URL})")

    st.link_button(
        "Google 뉴스에서 최근 기사 확인",
        news_url,
        help="지역 필수 · 특보 중 하나 이상 · 최근 7일",
        on_click="ignore",
        width="stretch",
    )
    st.caption("뉴스는 외부 참고정보이며 위험도·발송·보고서에 반영되지 않습니다.")


def _render_cctv_status(feed: CctvFeed | None) -> None:
    count = len(feed.cctvs) if feed and feed.status is ContextStatus.LIVE else 0
    with st.expander(f"인근 교통 CCTV {count}곳", expanded=False):
        if feed is None or feed.status is ContextStatus.NOT_CONFIGURED:
            st.info(
                "ITS CCTV API 연동 준비 중입니다. "
                "인증키를 설정하면 지도에 인근 CCTV가 표시됩니다."
            )
        elif feed.status is ContextStatus.ERROR:
            st.warning(feed.detail or "인근 CCTV를 조회하지 못했습니다.")
            st.caption("기상청 관제·Telegram·PDF 기능은 계속 사용할 수 있습니다.")
        elif not feed.cctvs:
            st.info("20km 내에 ITS가 제공하는 도로 CCTV가 없습니다.")
            st.caption("CCTV가 없다는 것은 현장이 안전하다는 판정이 아닙니다.")
        else:
            if "실패" in feed.detail:
                st.warning(feed.detail)
            else:
                st.caption(
                    f"{feed.detail} · {feed.fetched_at:%m-%d %H:%M:%S} "
                    "영상 주소 조회 · 최대 1분 캐시"
                )
            for item in feed.cctvs:
                source_timing, _, source_time_known = describe_cctv_timing(
                    item,
                    feed.fetched_at,
                )
                st.write(
                    f"🎥 **{item.name}**  \n"
                    f"{item.road_type} · 직선거리 {item.distance_km:.1f}km  \n"
                    f"{'🕒' if source_time_known else '⚠️'} {source_timing}"
                )
            st.caption(
                "지도의 카메라 마커를 누르면 큰 영상 작업창이 열립니다. "
                "작업창에서 1분 캐시를 우회해 즉시 다시 요청할 수 있습니다."
            )
        st.caption(
            "시설 자체·하천 CCTV가 아닌 인근 고속도로·국도 영상입니다."
        )
        st.link_button(
            "ITS 공식 교통지도에서 확인",
            OFFICIAL_MAP_URL,
            icon=":material/map:",
            width="stretch",
        )
        st.markdown(f"[출처 · ITS 국가교통정보센터]({CCTV_SOURCE_URL})")
