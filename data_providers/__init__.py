"""
데이터 제공자(Data Provider) 패키지

향후 홍수통제소 API, 산림청 API 등 추가 데이터 소스를 쉽게 통합할 수 있도록
데이터 제공자 인터페이스 및 레지스트리를 정의합니다.

새로운 데이터 소스 추가 방법:
1. BaseWarningProvider를 상속하는 클래스를 data_providers/ 아래에 생성
2. get_warnings(), get_weather_at() 메서드를 구현
3. register_provider()로 등록

예시:
    from data_providers import BaseWarningProvider, register_provider

    class FloodProvider(BaseWarningProvider):
        source_name = "홍수통제소"
        def get_warnings(self): ...
        def get_weather_at(self, lat, lon): ...

    register_provider(FloodProvider())
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional
import pandas as pd


class BaseWarningProvider(ABC):
    """
    재난/기상 경보 데이터를 제공하는 기본 인터페이스.
    모든 데이터 소스(기상청, 홍수통제소, 산림청 등)는 이 인터페이스를 구현합니다.
    """

    source_name: str = "unknown"  # 데이터 소스 표시명

    @abstractmethod
    def get_warnings(self, region_filter: Optional[str] = None) -> pd.DataFrame:
        """
        현재 발효 중인 경보/특보 목록을 반환합니다.

        Returns:
            DataFrame with columns:
                - region_up: 상위 지역명 (예: 경상북도)
                - region: 세부 지역명 (예: 포항시)
                - type: 경보 유형 (예: 호우, 홍수, 산사태)
                - level: 등급 (예: 주의보, 경보)
                - source: 데이터 출처 (예: 기상청, 홍수통제소)
        """
        pass

    @abstractmethod
    def get_weather_at(self, lat: float, lon: float) -> Dict[str, str]:
        """
        특정 위치의 현재 기상/관측 데이터를 반환합니다.

        Args:
            lat: 위도
            lon: 경도

        Returns:
            dict: 관측값 딕셔너리 (예: {"기온(℃)": "25.0", "강수량(mm)": "0.0"})
        """
        pass

    def get_risk_factors(self, lat: float, lon: float) -> List[Dict]:
        """
        특정 위치에 대한 추가 위험 요소를 반환합니다.
        (선택적 구현 - 홍수위험도, 산사태위험도 등)

        Returns:
            list of dict: [{"factor": "홍수위험도", "value": 3, "max": 5}, ...]
        """
        return []


# ========================================
# 프로바이더 레지스트리
# ========================================
_providers: List[BaseWarningProvider] = []


def register_provider(provider: BaseWarningProvider):
    """데이터 제공자를 레지스트리에 등록합니다."""
    _providers.append(provider)


def get_all_providers() -> List[BaseWarningProvider]:
    """등록된 모든 데이터 제공자를 반환합니다."""
    return _providers


def get_all_warnings(region_filter: Optional[str] = None) -> pd.DataFrame:
    """모든 등록된 데이터 소스로부터 경보를 수집하여 통합 반환합니다."""
    all_warnings = []
    for provider in _providers:
        try:
            df = provider.get_warnings(region_filter=region_filter)
            if not df.empty:
                all_warnings.append(df)
        except Exception:
            pass

    if all_warnings:
        return pd.concat(all_warnings, ignore_index=True)
    return pd.DataFrame(columns=["region_up", "region", "type", "level", "source"])
