"""서비스 계정으로 Google Sheet 연락처를 읽는 어댑터."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any
from urllib.parse import quote

import requests

from safety_dashboard.alerts.contacts import ContactDataError, build_contact_directory
from safety_dashboard.alerts.domain import ContactDirectory


SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"


class GoogleSheetContactProvider:
    def __init__(
        self,
        spreadsheet_id: str,
        sheet_range: str = "Recipients!A:E",
        *,
        session: Any | None = None,
        timeout: float = 7,
    ) -> None:
        self.spreadsheet_id = spreadsheet_id.strip()
        self.sheet_range = sheet_range.strip() or "Recipients!A:E"
        self._session = session
        self.timeout = timeout

    def fetch(self, valid_facility_ids: Sequence[str]) -> ContactDirectory:
        if not self.spreadsheet_id:
            raise ContactDataError("Google Sheet ID가 설정되지 않았습니다.")
        session = self._session or self._authorized_session()
        url = (
            "https://sheets.googleapis.com/v4/spreadsheets/"
            f"{quote(self.spreadsheet_id, safe='')}/values/"
            f"{quote(self.sheet_range, safe='')}"
        )
        try:
            response = session.get(url, timeout=self.timeout)
            response.raise_for_status()
            values = response.json().get("values", [])
        except (requests.RequestException, ValueError, AttributeError) as exc:
            raise ContactDataError(
                f"Google Sheet 연락처 조회 실패 ({type(exc).__name__})"
            ) from exc
        if not values:
            raise ContactDataError("Google Sheet 연락처 표가 비어 있습니다.")
        headers = [str(value).strip() for value in values[0]]
        rows = []
        for values_row in values[1:]:
            padded = list(values_row) + [""] * max(0, len(headers) - len(values_row))
            rows.append(dict(zip(headers, padded, strict=False)))
        return build_contact_directory(
            rows,
            valid_facility_ids,
            fetched_at=dt.datetime.now(dt.timezone.utc),
        )

    @staticmethod
    def _authorized_session() -> Any:
        try:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession

            credentials, _ = google.auth.default(scopes=(SHEETS_SCOPE,))
            return AuthorizedSession(credentials)
        except Exception as exc:
            raise ContactDataError("Google 서비스 계정 인증을 구성하지 못했습니다.") from exc
