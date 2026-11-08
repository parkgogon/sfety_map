"""요청 시 공식 문자 한 페이지 조회. 등록 시 공급자 원본을 서명으로 검증."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
from typing import Literal

from pydantic import Field
from safety_dashboard.application.context_info import KST
from safety_dashboard.application.message_analysis import StrictModel
from safety_dashboard.application.message_records import MessageSource

PROVINCES = ("대구광역시", "경상북도", "부산광역시", "울산광역시", "경상남도")


class FeedRequest(StrictModel):
    region: Literal["대구광역시", "경상북도", "부산광역시", "울산광역시", "경상남도"]
    date: dt.date
    page: int = Field(default=1, ge=1, le=3)


class ImportOfficial(StrictModel):
    import_token: str = Field(min_length=10, max_length=40000)


class OfficialFeedService:
    def __init__(self, provider, secret: str, *, now=lambda: dt.datetime.now(KST)):
        self.provider, self.secret, self.now = provider, secret.encode(), now

    def fetch(self, request: FeedRequest):
        today = self.now().date()
        if not today - dt.timedelta(days=6) <= request.date <= today:
            raise ValueError("오늘을 포함한 최근 7일 중 하루를 선택해 주세요.")
        if not self.provider.configured:
            return {"status": "NOT_CONFIGURED", "messages": [], "detail": "공식 재난문자 조회가 설정되지 않았습니다."}
        page = self.provider.fetch_page(request.region, request.date, request.page, 50)
        fetched = self.now().isoformat()
        messages = []
        for row in page["messages"]:
            if row.created_at.astimezone(KST).date() != request.date:
                page["skipped"] += 1
                continue
            try:
                canonical = MessageSource(text=row.content, source="행정안전부 공개 재난문자 API",
                    issued_at=row.created_at, recipient_regions=[r for r in row.regions if r != "-"]).canonical()
            except ValueError:
                page["skipped"] += 1
                continue
            payload = {"message": canonical, "official_id": row.id, "fetched_at": fetched,
                       "expires_at": int(self.now().timestamp()) + 900, "audience": "official-message-import-v1"}
            raw = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()).decode()
            signature = hmac.new(self.secret, raw.encode(), hashlib.sha256).hexdigest()
            messages.append({"official_id": row.id, "message": canonical, "import_token": f"{raw}.{signature}",
                             "disaster_type": row.disaster_type, "emergency_step": row.emergency_step})
        return {"status": "LIVE", "messages": messages, "region": request.region, "date": request.date.isoformat(),
                "page": request.page, "page_size": 50, "fetched_at": fetched,
                "has_more": page["has_more"], "page_limit_reached": request.page == 3 and page["has_more"],
                "skipped": page["skipped"], "detail": "선택한 지역·하루의 요청 페이지입니다. 전체 상시 감시 결과가 아닙니다."}

    def verify(self, token):
        try:
            raw, signature = token.split(".")
            expected = hmac.new(self.secret, raw.encode(), hashlib.sha256).hexdigest()
            if not self.secret or not hmac.compare_digest(signature, expected):
                raise ValueError()
            payload = json.loads(base64.b64decode(raw, altchars=b"-_", validate=True))
            if payload["audience"] != "official-message-import-v1" or self.now().timestamp() >= payload["expires_at"]:
                raise ValueError()
            message = MessageSource.model_validate(payload["message"]).canonical()
            identifier = payload["official_id"]
            if not isinstance(identifier, str) or not 1 <= len(identifier) <= 200:
                raise ValueError()
            return message, identifier, payload["fetched_at"]
        except (ValueError, KeyError, TypeError, UnicodeError):
            raise ValueError("공식 문자 확인 정보가 만료되었거나 올바르지 않습니다. 목록을 다시 조회해 주세요.") from None
