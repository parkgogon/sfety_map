"""선택 시설의 공식 재난문자와 외부 뉴스 링크를 표시합니다."""

from __future__ import annotations

import streamlit as st

from safety_dashboard.adapters.cctv import (
    OFFICIAL_MAP_URL,
    SOURCE_PAGE_URL as CCTV_SOURCE_URL,
)
from safety_dashboard.adapters.disaster_messages import SOURCE_PAGE_URL
from safety_dashboard.application.cctv_directions import describe_cctv_direction
from safety_dashboard.application.context_info import describe_cctv_timing
from safety_dashboard.domain.enums import ContextStatus, DataHealth
from safety_dashboard.domain.models import (
    CctvFeed,
    DisasterMessageFeed,
    FacilityRegion,
    WeatherObservation,
)


def render_facility_context(
    region: FacilityRegion | None,
    feed: DisasterMessageFeed | None,
    news_url: str,
    cctv_feed: CctvFeed | None = None,
    cctv_direction_warning: str = "",
    weather: WeatherObservation | None = None,
) -> None:
    if weather is not None:
        _render_weather(weather)
    _render_cctv_status(cctv_feed, cctv_direction_warning)
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

    _render_news_link(news_url)


def _render_weather(weather: WeatherObservation) -> None:
    with st.expander("현재 기상 실황", expanded=True):
        if weather.health is DataHealth.ERROR:
            st.warning(weather.message or "현재 기상을 조회하지 못했습니다.")
            st.caption("기상 실황 오류는 특보·위험도 계산에 영향을 주지 않습니다.")
            return
        temperature = _measurement(weather.temperature_c, "℃")
        rainfall = _measurement(weather.rainfall_1h_mm, "mm")
        wind_speed = _measurement(weather.wind_speed_ms, "m/s")
        direction = _wind_direction(weather.wind_direction_deg)
        st.markdown(
            '<div class="weather-grid">'
            f'<div><span>기온</span><b>{temperature}</b></div>'
            f'<div><span>1시간 강수</span><b>{rainfall}</b></div>'
            f'<div><span>풍속</span><b>{wind_speed}</b></div>'
            f'<div><span>풍향</span><b>{direction}</b></div>'
            '</div>',
            unsafe_allow_html=True,
        )
        st.caption(
            f"관측 기준 · {weather.observed_at:%Y-%m-%d %H:%M} · "
            f"{weather.message or '기상청 초단기실황'}"
        )


def _measurement(value: float | None, unit: str) -> str:
    return "—" if value is None else f"{value:g}{unit}"


def _wind_direction(value: float | None) -> str:
    if value is None:
        return "—"
    labels = ("북", "북동", "동", "남동", "남", "남서", "서", "북서")
    label = labels[int((value % 360 + 22.5) // 45) % 8]
    return f"{label} {value:g}°"


def _render_news_link(news_url: str) -> None:
    with st.container(key="news-actions"):
        link_column, help_column = st.columns(
            (1, 0.12),
            gap="small",
            vertical_alignment="center",
        )
        link_column.link_button(
            "Google 뉴스에서 최근 기사 확인",
            news_url,
            on_click="ignore",
            width="stretch",
        )
        with help_column.popover(
            "?",
            help="Google 뉴스 안내",
            width="stretch",
        ):
            st.markdown("**검색 기준**")
            st.write("시설 관할 지역 · 적용 특보 · 최근 7일")
            st.caption(
                "뉴스는 외부 참고정보이며 위험도·발송·보고서에 "
                "반영되지 않습니다."
            )


def _render_cctv_status(
    feed: CctvFeed | None,
    direction_warning: str = "",
) -> None:
    count = len(feed.cctvs) if feed and feed.status is ContextStatus.LIVE else 0
    warning_label = " · 방향 설정 확인" if direction_warning else ""
    with st.expander(
        f"인근 교통 CCTV {count}곳{warning_label}",
        expanded=False,
    ):
        if direction_warning:
            st.warning(
                "CCTV 방향 설정을 적용하지 못했습니다. "
                "방향 화살표만 비활성화됩니다."
            )
            st.caption(direction_warning)
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
                    f"🧭 {describe_cctv_direction(item)}  \n"
                    f"{'🕒' if source_time_known else '⚠️'} {source_timing}"
                )
                if item.direction_source:
                    st.caption(f"방향 검증 근거 · {item.direction_source}")
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
