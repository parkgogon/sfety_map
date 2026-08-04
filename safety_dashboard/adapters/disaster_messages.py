"""행정안전부 긴급재난문자 API 어댑터."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping
from typing import Any

import requests

from safety_dashboard.application.context_info import (
    KST,
    select_relevant_disaster_messages,
)
from safety_dashboard.domain.enums import ContextStatus
from safety_dashboard.domain.models import (
    DisasterMessage,
    DisasterMessageFeed,
    FacilityRegion,
)


DEFAULT_API_URL = "https://www.safetydata.go.kr/V2/api/DSSP-IF-00247"
SOURCE_PAGE_URL = "https://www.safetydata.go.kr/disaster-data/view?dataSn=228"


class DisasterMessageDataError(ValueError):
    pass


class SafetyDataDisasterMessageProvider:
    def __init__(
        self,
        api_key: str,
        api_url: str = DEFAULT_API_URL,
        timeout: float = 7,
    ) -> None:
        self.api_key = str(api_key or "").strip()
        self.api_url = str(api_url or DEFAULT_API_URL).strip()
        self.timeout = timeout

    def fetch_recent(
        self,
        region: FacilityRegion,
        since: dt.datetime,
    ) -> DisasterMessageFeed:
        fetched_at = dt.datetime.now(KST)
        if not self.api_key or self.api_key == "YOUR_SAFETY_DATA_API_KEY":
            return DisasterMessageFeed(
                status=ContextStatus.NOT_CONFIGURED,
                messages=(),
                fetched_at=fetched_at,
                detail="재난문자 API 키가 설정되지 않았습니다.",
            )
        try:
            response = requests.get(
                self.api_url,
                params={
                    "serviceKey": self.api_key,
                    "pageNo": 1,
                    "numOfRows": 100,
                    "returnType": "json",
                    "crtDt": since.astimezone(KST).strftime("%Y%m%d")
                    if since.tzinfo
                    else since.strftime("%Y%m%d"),
                    "rgnNm": region.query_name,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            messages = parse_disaster_response(response.json())
            selected = select_relevant_disaster_messages(
                messages,
                region,
                since,
                limit=5,
            )
        except (requests.RequestException, ValueError, TypeError) as exc:
            return DisasterMessageFeed(
                status=ContextStatus.ERROR,
                messages=(),
                fetched_at=fetched_at,
                detail=f"재난문자를 조회하지 못했습니다 ({type(exc).__name__}).",
            )
        return DisasterMessageFeed(
            status=ContextStatus.LIVE,
            messages=selected,
            fetched_at=fetched_at,
            detail=f"행정안전부 재난문자 · {region.district}",
        )


def parse_disaster_response(payload: object) -> tuple[DisasterMessage, ...]:
    if not isinstance(payload, (dict, list)):
        raise DisasterMessageDataError("API 응답이 JSON 객체가 아닙니다.")
    error = _find_api_error(payload)
    if error:
        raise DisasterMessageDataError(error)
    rows = _find_message_rows(payload)
    if rows is None:
        if _is_empty_response(payload):
            return ()
        raise DisasterMessageDataError("재난문자 목록을 찾을 수 없습니다.")

    result: list[DisasterMessage] = []
    for row in rows:
        try:
            message_id = str(_value(row, "SN", "sn")).strip()
            content = str(_value(row, "MSG_CN", "msgCn", "msg_cn")).strip()
            created_at = _parse_time(_value(row, "CRT_DT", "crtDt", "crt_dt"))
        except (KeyError, TypeError, ValueError):
            continue
        if not message_id or not content:
            continue
        result.append(
            DisasterMessage(
                id=message_id,
                created_at=created_at,
                emergency_step=str(
                    _value(row, "EMRG_STEP_NM", "emrgStepNm", default="-")
                ).strip() or "-",
                disaster_type=str(
                    _value(row, "DST_SE_NM", "dstSeNm", default="기타")
                ).strip() or "기타",
                content=content,
                regions=_split_regions(
                    str(_value(row, "RCPTN_RGN_NM", "rcptnRgnNm", default=""))
                ),
            )
        )
    if rows and not result:
        raise DisasterMessageDataError("재난문자 필수 필드를 해석할 수 없습니다.")
    return tuple(result)


def _find_message_rows(value: object) -> list[Mapping[str, Any]] | None:
    if isinstance(value, list):
        mappings = [item for item in value if isinstance(item, Mapping)]
        if mappings and any(
            "SN" in item or "MSG_CN" in item or "msgCn" in item
            for item in mappings
        ):
            return mappings
        for item in value:
            found = _find_message_rows(item)
            if found is not None:
                return found
    if isinstance(value, Mapping):
        if "SN" in value and ("MSG_CN" in value or "msgCn" in value):
            return [value]
        for item in value.values():
            found = _find_message_rows(item)
            if found is not None:
                return found
    return None


def _find_api_error(value: object) -> str:
    if isinstance(value, Mapping):
        for key in ("returnAuthMsg", "errMsg", "errorMessage"):
            if value.get(key):
                return "재난문자 API가 요청을 거부했습니다."
        result_code = value.get("resultCode")
        if result_code not in (None, "", "00", 0, "0"):
            return "재난문자 API가 오류 상태를 반환했습니다."
        for item in value.values():
            found = _find_api_error(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_api_error(item)
            if found:
                return found
    return ""


def _is_empty_response(payload: object) -> bool:
    if isinstance(payload, Mapping):
        for key in ("totalCount", "TOTAL_COUNT", "totalCnt"):
            if key in payload and str(payload[key]).strip() in ("", "0"):
                return True
        return any(_is_empty_response(item) for item in payload.values())
    if isinstance(payload, list):
        return not payload or any(_is_empty_response(item) for item in payload)
    return False


def _value(
    row: Mapping[str, Any],
    *keys: str,
    default: object = ...,
) -> object:
    for key in keys:
        if key in row:
            return row[key]
    if default is not ...:
        return default
    raise KeyError(keys[0])


def _parse_time(value: object) -> dt.datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("재난문자 생성 시각이 없습니다.")
    normalized = text.replace("/", "-").replace(".", "-")
    normalized = re.sub(r"\s+", " ", normalized)
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError:
        parsed = None
        for pattern in ("%Y%m%d%H%M%S", "%Y%m%d %H%M%S", "%Y-%m-%d %H:%M"):
            try:
                parsed = dt.datetime.strptime(normalized, pattern)
                break
            except ValueError:
                continue
        if parsed is None:
            raise ValueError("재난문자 생성 시각을 해석할 수 없습니다.")
    return parsed.replace(tzinfo=KST) if parsed.tzinfo is None else parsed.astimezone(KST)


def _split_regions(value: str) -> tuple[str, ...]:
    return tuple(
        item.strip()
        for item in re.split(r"[,;|]", value)
        if item.strip()
    ) or ("-",)
