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


def recent_request_reserve(limit):
    """Keep the default 289/161 split, leaving history capacity for smaller quotas."""
    return max(0, min(limit-1, (limit*289+449)//450))


class OfficialRequestBudget:
    """Reserve before HTTP; failures also count. Never refund uncertain attempts."""
    KEY = "official-request-budget"
    WINDOW = dt.timedelta(hours=24)

    def __init__(self, store, limit=450, *, now=lambda: dt.datetime.now(UTC), latest_reserve=0):
        if not 1 <= limit <= 450:
            raise ValueError("공식 문자 조회 상한은 1~450회여야 합니다.")
        self.store, self.limit, self.now = store, limit, now
        self.latest_reserve = min(limit, max(0, latest_reserve))

    def _live(self, value, now):
        return sorted(s for s in (value or {}).get("starts", []) if moment(s) > now-self.WINDOW)

    def _background(self, value, now):
        # Old unclassified reservations count as background during migration.
        return self._live({"starts": (value or {}).get("background_starts", (value or {}).get("starts", []))}, now)

    def reserve(self, *, priority="normal"):
        now = self.now()

        def reserve(values):
            starts = self._live(values[self.KEY], now)
            background = self._background(values[self.KEY], now)
            if len(starts) >= self.limit:
                raise FeedRequestLimit(stamp(moment(starts[-self.limit])+self.WINDOW))
            capacity = self.limit-self.latest_reserve
            if self.latest_reserve and priority != "latest" and len(background) >= capacity:
                retry = moment(background[-capacity])+self.WINDOW if capacity else now+self.WINDOW
                raise FeedRequestLimit(stamp(retry))
            starts.append(stamp(now))
            if priority != "latest":
                background.append(stamp(now))
            return {self.KEY: {"starts": starts, "background_starts": background}}, None

        try:
            self.store.run([self.KEY], reserve)
        except FeedRequestLimit:
            raise
        except Exception:
            raise FeedBudgetUnavailable("문자 조회 한도를 확인하지 못해 외부 조회를 시작하지 않았습니다.") from None

    def status(self):
        now = self.now()
        starts = self._live(self.store.get(self.KEY), now)
        background = self._background(self.store.get(self.KEY), now)
        return {"limit": self.limit, "used": len(starts), "remaining": max(0, self.limit-len(starts)),
                "latest_reserve": self.latest_reserve,
                "background_remaining": min(max(0, self.limit-len(starts)), max(0, self.limit-self.latest_reserve-len(background))) if self.latest_reserve else max(0, self.limit-len(starts)),
                "window_hours": 24, "next_available_at": stamp(moment(starts[-self.limit])+self.WINDOW) if len(starts) >= self.limit else None}
