"""Bounded, resumable official collection, independent of alert dispatch."""
from __future__ import annotations

import datetime as dt
import time
import uuid

from pydantic import ValidationError

from safety_dashboard.application.context_info import KST
from safety_dashboard.application.message_pipeline import MessageAnalysisQueue, PipelineLeases, UTC, moment, stamp, task_id
from safety_dashboard.application.message_records import MessageSource, content_hash
from safety_dashboard.application.message_feed_budget import FeedRequestLimit
from safety_dashboard.application.message_feed import PROVINCES
from safety_dashboard.application.message_analysis import REGION_ALIASES


TARGET_NAMES = PROVINCES + tuple(REGION_ALIASES[name] for name in PROVINCES)


def recipient_scope(regions):
    def matches(value, names):
        return any(value == name or value.startswith(name+" ") for name in names)
    if any(matches(r, ("전국", "대한민국")) or matches(r, TARGET_NAMES) for r in regions):
        return True
    names = tuple(REGION_ALIASES) + tuple(REGION_ALIASES.values())
    if not regions or any(not matches(r, names) for r in regions):
        return None
    return False


class OfficialMessageCollector:
    def __init__(self, provider, records, store, settings, *, now=lambda: dt.datetime.now(UTC), clock=time.monotonic):
        self.provider, self.records, self.store, self.settings = provider, records, store, settings
        self.now, self.clock = now, clock
        self.leases, self.queue = PipelineLeases(store), MessageAnalysisQueue(store)

    def run(self):
        if not self.settings.enabled or not self.settings.contract_verified or not self.provider.configured:
            return {"state": "disabled"}
        owner = uuid.uuid4().hex
        if not self.leases.acquire("collection-lease", owner, self.now()):
            return {"state": "busy"}
        state = self.store.get("collection-state") or {}
        started = self.clock()
        pages, imported = 0, 0

        def save():
            self.leases.write("collection-lease", owner, self.now(), "collection-state", state)

        try:
            now = self.now()
            if not state.get("start_at"):
                start = self.settings.start_at or now
                if start > now:
                    raise ValueError("future_start")
                state["start_at"] = stamp(start)
            state.update(last_attempt_at=stamp(now), last_error="")
            today = now.astimezone(KST).date()
            if not state.get("work"):
                anchor = moment(state.get("last_success_at") or state["start_at"]).astimezone(KST).date()
                wanted = min(anchor, today) - dt.timedelta(days=1)
                first = max(wanted, today - dt.timedelta(days=self.settings.catchup_days - 1))
                state.update(cycle_skipped=0, coverage_gap=first > wanted,
                             work=[{"region": None, "date": (today-dt.timedelta(days=i)).isoformat(), "page": 1, "offset": 0}
                                   for i in range((today-first).days+1)])
            else:
                # A midnight rollover must not wait behind yesterday's remaining pages.
                newest = dt.date.fromisoformat(max(part["date"] for part in state["work"]))
                if newest < today:
                    wanted = newest + dt.timedelta(days=1)
                    first = max(wanted, today-dt.timedelta(days=self.settings.catchup_days-1))
                    state["coverage_gap"] = state.get("coverage_gap", False) or first > wanted
                    state["work"] = [{"region": None, "date": (today-dt.timedelta(days=i)).isoformat(), "page": 1, "offset": 0}
                                     for i in range((today-first).days+1)] + state["work"]
            save()
            while state["work"] and pages < self.settings.max_pages and self.clock()-started < self.settings.scan_seconds:
                part = state["work"][0]
                fetched_at = stamp(self.now())
                page = self.provider.fetch_page(part["region"], dt.date.fromisoformat(part["date"]), part["page"], 100)
                pages += 1
                if not self.leases.owns("collection-lease", owner, self.now()):
                    return {"state": "lease_expired", "pages": pages}
                rows = page["messages"]
                fingerprint = content_hash({"rows": [self._signature(row) for row in rows], "more": page["has_more"]})
                if part.get("verify_head"):
                    state["work"].pop(0)
                    if fingerprint != part["head_hash"]:
                        state["work"].append({"region": part["region"], "date": part["date"], "page": 1, "offset": 0})
                    save()
                    continue
                if part.get("page_hash") != fingerprint:
                    part.update(page_hash=fingerprint, offset=0)
                if part["page"] == 1:
                    part["head_hash"] = fingerprint
                if part["offset"] == 0:
                    state["cycle_skipped"] += page.get("skipped", 0)
                while part["offset"] < len(rows) and self.clock()-started < self.settings.scan_seconds:
                    row = rows[part["offset"]]
                    # crtDt is documented as a start date. Accept exact-day or range responses.
                    row_day = row.created_at.astimezone(KST).date()
                    scope = recipient_scope(row.regions)
                    if not dt.date.fromisoformat(part["date"]) <= row_day <= today:
                        state["cycle_skipped"] += 1
                    elif scope is None:
                        state["cycle_skipped"] += 1
                    elif not scope:
                        pass
                    else:
                        try:
                            message = MessageSource(text=row.content, source="행정안전부 공개 재난문자 API",
                                                    issued_at=row.created_at, recipient_regions=[r for r in row.regions if r != "-"]).canonical()
                        except (ValidationError, ValueError):
                            state["cycle_skipped"] += 1
                        else:
                            self._import(message, row.id, fetched_at, state["start_at"])
                            imported += 1
                    part["offset"] += 1
                    state["last_progress_at"] = stamp(self.now())
                    if part["offset"] % 10 == 0:
                        save()  # Advance only after durable record and queue writes.
                if part["offset"] < len(rows):
                    save()
                    break
                state["work"].pop(0)
                if page["has_more"]:
                    state["work"].append({"region": part["region"], "date": part["date"], "page": part["page"]+1,
                                          "offset": 0, "head_hash": part["head_hash"]})
                elif part["page"] > 1:
                    state["work"].append({"region": part["region"], "date": part["date"], "page": 1,
                                          "offset": 0, "verify_head": True, "head_hash": part["head_hash"]})
                if not state["work"] and not state["cycle_skipped"] and not state["coverage_gap"]:
                    state["last_success_at"] = stamp(self.now())
                save()
            return {"state": "partial" if state["work"] or state["cycle_skipped"] or state["coverage_gap"] else "ok",
                    "pages": pages, "observed": imported}
        except FeedRequestLimit as error:
            state.update(last_error="", request_limited_at=stamp(self.now()), request_retry_at=error.retry_at)
            save()
            return {"state": "request_limit", "pages": pages}
        except Exception:
            # Never store URLs, provider payloads, keys or arbitrary exception messages.
            state.update(last_attempt_at=stamp(self.now()), last_error="collection_failed")
            if self.leases.owns("collection-lease", owner, self.now()):
                save()
            return {"state": "error", "pages": pages}
        finally:
            self.leases.release("collection-lease", owner)

    @staticmethod
    def _signature(row):
        return {"id": row.id, "text": row.content, "issued_at": row.created_at.isoformat(), "regions": list(row.regions)}

    def _import(self, message, identifier, fetched_at, start_at):
        previous = self.records.store.get(self.records.official_record_id(identifier))
        if moment(message["issued_at"]) < moment(start_at) and not previous:
            return
        saved = self.records.register_official(message, identifier, fetched_at)["record"]
        if previous and previous["source_revision"] != saved["source_revision"]:
            self.queue.finish(task_id(previous), "obsolete", self.now(), "source_changed")
        # Re-observation repairs a crash between registration and enqueue, idempotently.
        if moment(saved["message"]["issued_at"]) >= moment(start_at) or saved["analysis_revision"]:
            self.queue.enqueue(saved, self.now())
