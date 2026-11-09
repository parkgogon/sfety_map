"""Latest page every five minutes; resumable history uses only spare feed quota."""
from __future__ import annotations

import datetime as dt
import uuid

from safety_dashboard.application.context_info import KST
from safety_dashboard.application.message_collection import OfficialMessageCollector
from safety_dashboard.application.message_feed_budget import FeedRequestLimit
from safety_dashboard.application.message_pipeline import moment, stamp
from safety_dashboard.application.message_records import content_hash


class LatestFirstMessageCollector(OfficialMessageCollector):
    def run(self):
        if not self.settings.enabled or not self.settings.contract_verified or not self.provider.configured:
            return {"state": "disabled"}
        owner = uuid.uuid4().hex
        if not self.leases.acquire("collection-lease", owner, self.now()):
            return {"state": "busy"}
        state = self.store.get("collection-state") or {}
        started, pages, observed, background_read = self.clock(), 0, 0, False

        def save():
            self.leases.write("collection-lease", owner, self.now(), "collection-state", state)

        try:
            now = self.now()
            today = now.astimezone(KST).date()
            if not state.get("start_at"):
                start = self.settings.start_at or now
                if start > now:
                    raise ValueError("future_start")
                state["start_at"] = stamp(start)
            # Preserve unfinished legacy partitions and the original start boundary.
            state.setdefault("work", [])
            state.setdefault("partition_skipped", {})
            state.setdefault("latest_skipped", {})
            state.setdefault("completed_heads", {})
            state.setdefault("coverage_gap", False)
            state.setdefault("cycle_ignored_before_start", 0)
            if state.get("cycle_skipped") and state.get("strategy") != "latest_first_v1":
                state["partition_skipped"]["legacy"] = state.get("cycle_skipped_reasons") or {"source_fields": state["cycle_skipped"]}
                # The legacy counter has no partition attribution. Recheck its full
                # bounded window before clearing it, preserving any unfinished pages.
                anchor = moment(state.get("last_success_at") or state["start_at"]).astimezone(KST).date()
                first = max(min(anchor, today)-dt.timedelta(days=1), today-dt.timedelta(days=self.settings.catchup_days-1))
                state["work"].extend(self._part((today-dt.timedelta(days=i)).isoformat()) for i in range((today-first).days+1))
                state["legacy_recheck"] = True
            state.update(strategy="latest_first_v1", last_attempt_at=stamp(now), last_error="")
            bucket = int(now.timestamp()) // 300
            latest_due = state.get("latest_bucket") != bucket
            if latest_due:
                # A timeout consumes this bucket as well as the shared HTTP reservation.
                state["latest_bucket"] = bucket
            hour = int(now.timestamp()) // 3600
            if state.get("backfill_hour") != hour:
                anchor = moment(state.get("last_backfill_success_at") or state.get("last_success_at") or state["start_at"]).astimezone(KST).date()
                wanted = min(anchor, today)-dt.timedelta(days=1)
                first = max(wanted, today-dt.timedelta(days=self.settings.catchup_days-1))
                state["coverage_gap"] |= first > wanted
                existing = {p["date"] for p in state["work"]}
                for i in range(1, (today-first).days+1):
                    date = (today-dt.timedelta(days=i)).isoformat()
                    if date not in existing:
                        state["work"].append(self._part(date))
                state["backfill_hour"] = hour
            save()

            def consume(part, priority):
                nonlocal pages, observed
                page = self.provider.fetch_page(None, dt.date.fromisoformat(part["date"]), part["page"], 100, priority=priority)
                pages += 1
                if not self.leases.owns("collection-lease", owner, self.now()):
                    raise RuntimeError("lease_expired")
                fingerprint = content_hash({"rows": [self._signature(row) for row in page["messages"]], "more": page["has_more"], "skipped": page.get("skipped", 0)})
                if part.get("page_hash") != fingerprint:
                    part.update(page_hash=fingerprint, offset=0)
                if part.get("verify_head"):
                    return page, fingerprint, True
                if part["page"] == 1:
                    part["head_hash"] = fingerprint
                    if priority == "latest" and part["offset"] == 0:
                        state["latest_skipped"] = {}
                    elif priority != "latest" and part["offset"] == 0:
                        state["partition_skipped"][part["date"]] = {}
                reasons = state["latest_skipped"] if priority == "latest" else state["partition_skipped"].setdefault(part["date"], {})

                def skip(reason, count=1):
                    reasons[reason] = reasons.get(reason, 0)+count

                if not part["offset"] and page.get("skipped"):
                    skip("source_fields", page["skipped"])
                while part["offset"] < len(page["messages"]) and self.clock()-started < self.settings.scan_seconds:
                    count, ignored = self._observe_row(page["messages"][part["offset"]], part["date"], today,
                        stamp(self.now()), state["start_at"], skip)
                    observed += count
                    state["cycle_ignored_before_start"] += ignored
                    part["offset"] += 1
                    state["last_progress_at"] = stamp(self.now())
                    if part["offset"] % 10 == 0:
                        save()
                return page, fingerprint, part["offset"] == len(page["messages"])

            if latest_due:
                date = today.isoformat()
                part = state.get("latest_part") or self._part(date)
                if part["date"] != date:
                    part = self._part(date)
                state["latest_part"] = part
                save()
                page, fingerprint, complete = consume(part, "latest")
                if complete:
                    state.pop("latest_part", None)
                    state["last_latest_observed_at"] = stamp(self.now())
                    if not state["latest_skipped"]:
                        state["last_latest_success_at"] = stamp(self.now())
                    pending = [p for p in state["work"] if p["date"] == date]
                    if not page["has_more"]:
                        state["work"] = [p for p in state["work"] if p["date"] != date]
                        state["completed_heads"][date] = fingerprint
                        state["partition_skipped"].pop(date, None)
                    elif not pending and state["completed_heads"].get(date) != fingerprint:
                        state["work"].insert(0, self._part(date, 2, head_hash=fingerprint))
                    elif pending and pending[0]["page"] == 1 and not pending[0].get("verify_head"):
                        state["work"].remove(pending[0])
                        state["work"].insert(0, self._part(date, 2, head_hash=fingerprint))
                save()

            while state["work"] and pages < self.settings.max_pages and self.clock()-started < self.settings.scan_seconds:
                part = state["work"][0]
                page, fingerprint, complete = consume(part, "background")
                background_read = True
                if not complete:
                    save()
                    break
                state["work"].pop(0)
                if part.get("verify_head"):
                    if fingerprint != part["head_hash"] or state["partition_skipped"].get(part["date"]):
                        state["work"].append(self._part(part["date"]))
                    else:
                        state["completed_heads"][part["date"]] = fingerprint
                elif page["has_more"]:
                    state["work"].append(self._part(part["date"], part["page"]+1, head_hash=part["head_hash"]))
                elif part["page"] > 1:
                    state["work"].append(self._part(part["date"], verify_head=True, head_hash=part["head_hash"]))
                else:
                    state["completed_heads"][part["date"]] = fingerprint
                save()

            # Bounded status metadata. Unfinished partitions are never discarded.
            floor = (today-dt.timedelta(days=self.settings.catchup_days)).isoformat()
            for key in ("completed_heads", "partition_skipped"):
                state[key] = {k: v for k, v in state[key].items() if k >= floor or k == "legacy" or any(p["date"] == k for p in state["work"])}
            if state.get("legacy_recheck") and not state["work"] and not state.get("latest_part"):
                state["partition_skipped"].pop("legacy", None)
                state.pop("legacy_recheck", None)
            if not state["work"] and not state.get("latest_part") and not state["latest_skipped"] and not any(state["partition_skipped"].values()) and not state["coverage_gap"]:
                state["last_success_at"] = stamp(self.now())
                if background_read:
                    state["last_backfill_success_at"] = stamp(self.now())
            self._summarize(state)
            save()
            return {"state": "partial" if state["work"] or state.get("latest_part") or state["cycle_skipped"] or state["coverage_gap"] else "ok", "pages": pages, "observed": observed}
        except FeedRequestLimit as error:
            self._summarize(state)
            state.update(request_limited_at=stamp(self.now()), request_retry_at=error.retry_at)
            save()
            return {"state": "request_limit", "pages": pages, "observed": observed}
        except Exception:
            self._summarize(state)
            state["last_error"] = "collection_failed"
            if self.leases.owns("collection-lease", owner, self.now()):
                save()
            return {"state": "error", "pages": pages}
        finally:
            self.leases.release("collection-lease", owner)

    @staticmethod
    def _part(date, page=1, **extra):
        return {"region": None, "date": date, "page": page, "offset": 0, **extra}

    @staticmethod
    def _summarize(state):
        reasons = {}
        for values in state.get("partition_skipped", {}).values():
            for reason, count in values.items():
                reasons[reason] = reasons.get(reason, 0)+count
        for reason, count in state.get("latest_skipped", {}).items():
            reasons[reason] = reasons.get(reason, 0)+count
        state.update(cycle_skipped=sum(reasons.values()), cycle_skipped_reasons=reasons)
