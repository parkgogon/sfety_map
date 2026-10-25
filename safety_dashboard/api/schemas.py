from __future__ import annotations
from typing import Literal
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from safety_dashboard.alerts.domain import ManualTelegramCategory


class ManualTelegramMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=3900)
    silent: bool = True
    action_label: str = Field(default="", max_length=80)
    action_url: str = Field(default="", max_length=500)


class AdminAccessRequest(BaseModel):
    password: str


class NearbyReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    label: str = Field(min_length=1, max_length=80)
    address: str = Field(default="", max_length=250)
    radius_km: float = Field(default=5, ge=0.1, le=50)

    @field_validator("radius_km")
    @classmethod
    def radius_step(cls, value: float) -> float:
        if Decimal(str(value)) * 10 % 1:
            raise ValueError("반경은 0.1km 단위로 입력해 주세요.")
        return value


class ManualTelegramDispatchRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=80)
    category: ManualTelegramCategory
    mode: Literal["live", "simulation"]
    note: str = Field(default="", max_length=200)
    facility_ids: list[str] = Field(min_length=1, max_length=300)
    warning_keys: list[str] = Field(min_length=1, max_length=200)
    messages: list[ManualTelegramMessageRequest] = Field(min_length=1, max_length=30)
    policy_version: str = Field(default="", max_length=80)
    temporary_policy: bool = False
    allow_duplicate: bool = False
