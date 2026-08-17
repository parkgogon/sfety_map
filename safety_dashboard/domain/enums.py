"""관제 도메인의 표준 상태와 등급."""

from __future__ import annotations

from enum import Enum


class DataHealth(str, Enum):
    LIVE = "LIVE"
    FALLBACK = "FALLBACK"
    STALE = "STALE"
    ERROR = "ERROR"
    SIMULATION = "SIMULATION"


class KmaFailureCategory(str, Enum):
    """KMA 조회 실패를 관리자용으로 분류한 내부 상태."""

    AUTH_CONFIG = "AUTH_CONFIG"
    QUOTA = "QUOTA"
    KMA_SERVER = "KMA_SERVER"
    KMA_ROUTE = "KMA_ROUTE"
    CLOUD_EGRESS = "CLOUD_EGRESS"
    RESPONSE_FORMAT = "RESPONSE_FORMAT"
    UNKNOWN = "UNKNOWN"

    @property
    def label(self) -> str:
        return {
            KmaFailureCategory.AUTH_CONFIG: "인증·설정",
            KmaFailureCategory.QUOTA: "사용량 제한",
            KmaFailureCategory.KMA_SERVER: "KMA 서버",
            KmaFailureCategory.KMA_ROUTE: "KMA API 통신경로",
            KmaFailureCategory.CLOUD_EGRESS: "Cloud Run 외부통신",
            KmaFailureCategory.RESPONSE_FORMAT: "응답 형식",
            KmaFailureCategory.UNKNOWN: "원인 미확정",
        }[self]


class ContextStatus(str, Enum):
    """핵심 관제와 독립적으로 로드되는 현장 참고정보의 상태."""

    LIVE = "LIVE"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    ERROR = "ERROR"


class WeatherLayerKind(str, Enum):
    """사용자 지도에 한 번에 표시할 실황 기상 레이어."""

    TEMPERATURE = "temperature"
    RAINFALL = "rainfall"
    WIND = "wind"


class WarningLevel(str, Enum):
    ADVISORY = "ADVISORY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


class RiskGrade(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNASSESSED = "UNASSESSED"
    NONE = "NONE"
