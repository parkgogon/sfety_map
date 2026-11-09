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
            if state.get("strategy") in {"latest_first_v1", "recent_window_v2"}:
                unfinished = state.pop("current_work", None) or state.pop("latest_part", None)
                if unfinished:
                    state.setdefault("work", []).insert(0, unfinished)
                state["strategy"] = "legacy_v1"
            if not state.get("work"):
                anchor = moment(state.get("last_success_at") or state["start_at"]).astimezone(KST).date()
                wanted = min(anchor, today) - dt.timedelta(days=1)
                first = max(wanted, today - dt.timedelta(days=self.settings.catchup_days - 1))
                state.update(cycle_skipped=0, cycle_skipped_reasons={}, cycle_ignored_before_start=0, coverage_gap=first > wanted,
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
            state.setdefault("coverage_gap", False)
            state.setdefault("cycle_skipped", 0)
            state.setdefault("cycle_skipped_reasons", {})
            state.setdefault("cycle_ignored_before_start", 0)
            def skip(reason, count=1):
                state["cycle_skipped"] += count
                state["cycle_skipped_reasons"][reason] = state["cycle_skipped_reasons"].get(reason, 0) + count
            while state["work"] and pages < self.settings.max_pages and self.clock()-started < self.settings.scan_seconds:
                part = state["work"][0]
                fetched_at = stamp(self.now())
                page = self.provider.fetch_page(part["region"], dt.date.fromisoformat(part["date"]), part["page"], 100)
                pages += 1
                if not self.leases.owns("collection-lease", owner, self.now()):
                    return {"state": "lease_expired", "pages": pages}
                rows = page["messages"]
                fingerprint = content_hash({"rows": [self._signature(row) for row in rows], "more": page["has_more"], "skipped": page.get("skipped", 0)})
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
                    if page.get("skipped", 0):
                        skip("source_fields", page["skipped"])
                while part["offset"] < len(rows) and self.clock()-started < self.settings.scan_seconds:
                    row = rows[part["offset"]]
                    observed, ignored = self._observe_row(row, part["date"], today, fetched_at, state["start_at"], skip)
                    imported += observed
                    state["cycle_ignored_before_start"] += ignored
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
                    followup = {"region": part["region"], "date": part["date"], "page": 1, "offset": 0}
                    if part.get("head_hash"):
                        followup.update(verify_head=True, head_hash=part["head_hash"])
                    state["work"].append(followup)
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

    def _observe_row(self, row, query_date, today, fetched_at, start_at, skip):
        """Common validation for legacy catch-up and latest-first collection."""
        row_day = row.created_at.astimezone(KST).date()
        scope = recipient_scope(row.regions)
        before_start = row.created_at < moment(start_at)
        valid_date = dt.date.fromisoformat(query_date) <= row_day <= today
        previous = self.records.store.get(self.records.official_record_id(row.id)) if valid_date and before_start and scope is not False else None
        if not valid_date:
            skip("query_date")
        elif before_start and not previous:
            return 0, 1
        elif scope is None:
            skip("recipient_region")
        elif scope:
            try:
                message = MessageSource(text=row.content, source="행정안전부 공개 재난문자 API",
                    issued_at=row.created_at, recipient_regions=[r for r in row.regions if r != "-"]).canonical()
            except (ValidationError, ValueError):
                skip("source_validation")
            else:
                self._import(message, row.id, fetched_at, start_at)
                return 1, 0
        return 0, 0

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
