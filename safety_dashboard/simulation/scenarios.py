"""모의훈련 시나리오 정의 및 특보/기상 가정 단일 소스."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Sequence

from safety_dashboard.domain.enums import WeatherLayerKind
from safety_dashboard.domain.models import Warning
from safety_dashboard.domain.risk_policy import RiskPolicy


@dataclass(frozen=True)
class SimulationWarningItem:
    region_up_code: str
    region_code: str
    region_up: str
    region: str
    warning_type: str
    raw_level: str


@dataclass(frozen=True)
class SimulationCenter:
    name: str
    latitude: float
    longitude: float
    warning_type: str
    raw_level: str


@dataclass(frozen=True)
class SimulationScenario:
    id: str
    label: str
    description: str
    recommended_layer: WeatherLayerKind
    warnings: tuple[SimulationWarningItem, ...]
    centers: tuple[SimulationCenter, ...]


MULTI_HAZARD_SCENARIO = SimulationScenario(
    id="multi_hazard_demo",
    label="종합 기상재난 모의훈련",
    description="포항 호우, 구미 강풍, 대구 폭염, 안동 태풍 복합 발생 시나리오",
    recommended_layer=WeatherLayerKind.WIND,
    warnings=(
        SimulationWarningItem("L1070000", "L1072400", "경상북도", "포항시", "호우", "경보"),
        SimulationWarningItem("L1070000", "L1070300", "경상북도", "구미시", "강풍", "주의보"),
        SimulationWarningItem("L1140000", "L1140100", "대구광역시", "대구중부", "폭염", "경보"),
        SimulationWarningItem("L1070000", "L1072700", "경상북도", "안동시", "태풍", "경보"),
    ),
    centers=(
        SimulationCenter("포항", 36.0190, 129.3435, "호우", "경보"),
        SimulationCenter("구미", 36.1195, 128.3446, "강풍", "주의보"),
        SimulationCenter("대구", 35.8714, 128.6014, "폭염", "경보"),
        SimulationCenter("안동", 36.5684, 128.7294, "태풍", "경보"),
    ),
)

SCENARIOS: dict[str, SimulationScenario] = {
    MULTI_HAZARD_SCENARIO.id: MULTI_HAZARD_SCENARIO,
}

DEFAULT_SCENARIO = MULTI_HAZARD_SCENARIO


def create_simulation_warnings(
    policy: RiskPolicy,
    scenario: SimulationScenario = DEFAULT_SCENARIO,
    now: dt.datetime | None = None,
) -> tuple[Warning, ...]:
    reference = (now or dt.datetime.now()).replace(minute=0, second=0, microsecond=0)
    return tuple(
        Warning(
            id=f"simulation-{index}",
            source="모의훈련",
            region_up_code=item.region_up_code,
            region_code=item.region_code,
            region_up=item.region_up,
            region=item.region,
            warning_type=item.warning_type,
            raw_level=item.raw_level,
            level=policy.normalize_level(item.raw_level),
            command="발표",
            issued_at=reference,
            effective_at=reference,
        )
        for index, item in enumerate(scenario.warnings, 1)
    )
