from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field
from safety_dashboard.alerts.domain import ManualTelegramCategory


class ManualTelegramMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=3900)
    silent: bool = True
    action_label: str = Field(default="", max_length=80)
    action_url: str = Field(default="", max_length=500)


class AdminAccessRequest(BaseModel):
    password: str


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
