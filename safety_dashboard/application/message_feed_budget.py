"""Shared rolling request budget for the 500/day official feed allowance."""
from __future__ import annotations

import datetime as dt

from safety_dashboard.application.message_pipeline import UTC, moment, stamp


class FeedRequestLimit(Exception):
    def __init__(self, retry_at):
        super().__init__("문자 조회 한도에 도달했습니다. 저장 기록과 남은 수집 작업은 유지됩니다.")
        self.retry_at = retry_at


class FeedBudgetUnavailable(Exception):
    pass


class OfficialRequestBudget:
    """Reserve before HTTP; failures also count. Never refund uncertain attempts."""
    KEY = "official-request-budget"
    WINDOW = dt.timedelta(hours=24)

    def __init__(self, store, limit=450, *, now=lambda: dt.datetime.now(UTC)):
        if not 1 <= limit <= 450:
            raise ValueError("공식 문자 조회 상한은 1~450회여야 합니다.")
        self.store, self.limit, self.now = store, limit, now

    def _live(self, value, now):
        return sorted(s for s in (value or {}).get("starts", []) if moment(s) > now-self.WINDOW)

    def reserve(self):
        now = self.now()

        def reserve(values):
            starts = self._live(values[self.KEY], now)
            if len(starts) >= self.limit:
                raise FeedRequestLimit(stamp(moment(starts[-self.limit])+self.WINDOW))
            starts.append(stamp(now))
            return {self.KEY: {"starts": starts}}, None

        try:
            self.store.run([self.KEY], reserve)
        except FeedRequestLimit:
            raise
        except Exception:
            raise FeedBudgetUnavailable("문자 조회 한도를 확인하지 못해 외부 조회를 시작하지 않았습니다.") from None

    def status(self):
        now = self.now()
        starts = self._live(self.store.get(self.KEY), now)
        return {"limit": self.limit, "used": len(starts), "remaining": max(0, self.limit-len(starts)),
                "window_hours": 24, "next_available_at": stamp(moment(starts[-self.limit])+self.WINDOW) if len(starts) >= self.limit else None}
