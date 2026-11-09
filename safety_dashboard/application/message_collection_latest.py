"""Repeated recent-day page walks. Neither ordering nor an unchanged head skips a tail."""
from __future__ import annotations

import datetime as dt
import uuid

from safety_dashboard.application.context_info import KST
from safety_dashboard.application.message_collection import OfficialMessageCollector
from safety_dashboard.application.message_feed_budget import FeedRequestLimit, recent_request_reserve
from safety_dashboard.application.message_pipeline import moment, stamp
from safety_dashboard.application.message_records import content_hash

STRATEGY = 'recent_window_v2'


class RecentWindowMessageCollector(OfficialMessageCollector):
    def run(self):
        if not self.settings.enabled or not self.settings.contract_verified or not self.provider.configured:
            return {'state': 'disabled'}
        owner = uuid.uuid4().hex
        if not self.leases.acquire('collection-lease', owner, self.now()):
            return {'state': 'busy'}
        state = self.store.get('collection-state') or {}
        started, pages, observed, background_read = self.clock(), 0, 0, False
        phase, lane = 'initialize', 'current'

        def save():
            self.leases.write('collection-lease', owner, self.now(), 'collection-state', state)

        try:
            now = self.now()
            today = now.astimezone(KST).date()
            date = today.isoformat()
            if not state.get('start_at'):
                start = self.settings.start_at or now
                if start > now:
                    raise ValueError('future_start')
                state['start_at'] = stamp(start)
            state.setdefault('work', [])
            state.setdefault('partition_skipped', {})
            state.setdefault('current_skipped', {})
            state.setdefault('coverage_gap', False)
            state.setdefault('cycle_ignored_before_start', 0)
            state.setdefault('lane_errors', {})
            if state.get('strategy') != STRATEGY:
                old = state.pop('latest_part', None)
                if old:
                    state['work'].insert(0, old)
                if state.get('last_error'):
                    state['lane_errors']['current'] = True
                if state.get('cycle_skipped'):
                    state['partition_skipped']['legacy'] = state.get('cycle_skipped_reasons') or {'source_fields': state['cycle_skipped']}
                    state['legacy_recheck'] = True
                # A completed/unchanged head is not evidence about any other page.
                state.pop('latest_skipped', None)
                state.pop('last_latest_success_at', None)
            state.update(strategy=STRATEGY, last_attempt_at=stamp(now))
            current = state.get('current_work')
            if current and current['date'] != date:
                state['work'].insert(0, current)
                state.pop('current_work', None)
                state.pop('current_next_at', None)
            hour = int(now.timestamp()) // 3600
            if state.get('backfill_hour') != hour:
                anchor = moment(state.get('last_backfill_success_at') or state.get('last_success_at') or state['start_at']).astimezone(KST).date()
                wanted = min(anchor, today)-dt.timedelta(days=1)
                first = max(wanted, today-dt.timedelta(days=self.settings.catchup_days-1))
                state['coverage_gap'] |= first > wanted
                existing = {p['date'] for p in state['work']}
                for offset in range(1, (today-first).days+1):
                    day = (today-dt.timedelta(days=offset)).isoformat()
                    if day not in existing:
                        state['work'].append(self._part(day))
                state['backfill_hour'] = hour
            # A new Korean date must start a full walk even if yesterday's next time is later.
            if not state.get('current_work') and (state.get('current_scan_date') != date
                    or not state.get('current_next_at') or moment(state['current_next_at']) <= now):
                state.update(current_work=self._part(date), current_scan_date=date,
                             current_scan_started_at=stamp(now), current_scan_reads=0, current_skipped={})
            phase = 'persist_progress'
            save()

            def consume(part, current_lane):
                nonlocal pages, observed, phase
                # Legacy verification markers become real page-one walks, not early exits.
                if part.pop('verify_head', False):
                    part.update(page=1, offset=0)
                    part.pop('page_hash', None)
                if current_lane:
                    state['current_scan_reads'] += 1
                phase = 'persist_progress'
                save()
                phase = 'fetch_page'
                page = self.provider.fetch_page(None, dt.date.fromisoformat(part['date']), part['page'], 100,
                                                priority='latest' if current_lane else 'background')
                pages += 1
                if not self.leases.owns('collection-lease', owner, self.now()):
                    raise RuntimeError('lease_expired')
                fingerprint = content_hash({'rows': [self._signature(r) for r in page['messages']],
                                            'more': page['has_more'], 'skipped': page.get('skipped', 0)})
                if part.get('page_hash') != fingerprint:
                    part.update(page_hash=fingerprint, offset=0)
                reasons = state['current_skipped'] if current_lane else state['partition_skipped'].setdefault(part['date'], {})
                if not current_lane and part['page'] == 1 and not part.get('scan_started'):
                    state['partition_skipped'][part['date']] = reasons = {}
                    part['scan_started'] = True

                def skip(reason, count=1):
                    reasons[reason] = reasons.get(reason, 0)+count

                if part['offset'] == 0 and page.get('skipped'):
                    skip('source_fields', page['skipped'])
                phase = 'observe_row'
                while part['offset'] < len(page['messages']) and self.clock()-started < self.settings.scan_seconds:
                    count, ignored = self._observe_row(page['messages'][part['offset']], part['date'], today,
                                                       stamp(self.now()), state['start_at'], skip)
                    observed += count
                    state['cycle_ignored_before_start'] += ignored
                    part['offset'] += 1
                    state['last_progress_at'] = stamp(self.now())
                    if part['offset'] % 10 == 0:
                        phase = 'persist_progress'
                        save()
                        phase = 'observe_row'
                state['lane_errors'].pop('current' if current_lane else 'background', None)
                return page, part['offset'] == len(page['messages'])

            bucket = int(now.timestamp()) // 300
            if state.get('current_work') and state.get('current_bucket') != bucket:
                state['current_bucket'] = bucket
                # Leave a page for unfinished history under the supported max_pages >= 2 config.
                current_cap = max(1, self.settings.max_pages-(1 if state['work'] else 0))
                while state.get('current_work') and pages < current_cap and self.clock()-started < self.settings.scan_seconds:
                    lane = 'current'
                    part = state['current_work']
                    page, complete = consume(part, True)
                    if not complete:
                        break
                    if page['has_more']:
                        state['current_work'] = self._part(date, part['page']+1)
                    else:
                        state.pop('current_work')
                        reads = state['current_scan_reads']
                        capacity = max(1, recent_request_reserve(self.settings.request_limit))
                        interval = max(300, ((reads*86400+capacity*300-1)//(capacity*300))*300)
                        state.update(last_current_scan_pages=reads, current_scan_interval_seconds=interval,
                                     last_current_scan_finished_at=stamp(self.now()),
                                     current_next_at=stamp(max(moment(state['current_scan_started_at'])+dt.timedelta(seconds=interval), self.now()+dt.timedelta(seconds=300))))
                        if not state['current_skipped']:
                            state['last_current_scan_success_at'] = stamp(self.now())
                    phase = 'persist_progress'
                    save()

            while state['work'] and pages < self.settings.max_pages and self.clock()-started < self.settings.scan_seconds:
                lane = 'background'
                part = state['work'][0]
                page, complete = consume(part, False)
                background_read = True
                if not complete:
                    break
                state['work'].pop(0)
                if page['has_more']:
                    state['work'].append(self._part(part['date'], part['page']+1))
                phase = 'persist_progress'
                save()
            floor = (today-dt.timedelta(days=self.settings.catchup_days)).isoformat()
            pending_dates = {p['date'] for p in state['work']}
            state['partition_skipped'] = {k:v for k,v in state['partition_skipped'].items()
                if k >= floor or k == 'legacy' or k in pending_dates}
            if state.get('legacy_recheck') and not state['work'] and not state.get('current_work'):
                state['partition_skipped'].pop('legacy', None)
                state.pop('legacy_recheck', None)
            self._summarize(state)
            if background_read and not state['work'] and not any(state['partition_skipped'].values()) and not state['lane_errors'].get('background'):
                state['last_backfill_success_at'] = stamp(self.now())
            if pages and not state['work'] and not state.get('current_work') and not state['cycle_skipped'] and not state['coverage_gap'] and not state.get('last_error'):
                state['last_success_at'] = stamp(self.now())
            phase = 'persist_progress'
            save()
            return {'state': 'error' if state.get('last_error') else 'partial' if state['work'] or state.get('current_work') or state['cycle_skipped'] or state['coverage_gap'] else 'ok',
                    'pages': pages, 'observed': observed}
        except FeedRequestLimit as error:
            self._summarize(state)
            state.update(request_limited_at=stamp(self.now()), request_retry_at=error.retry_at)
            save()
            return {'state': 'request_limit', 'pages': pages}
        except Exception:
            state.setdefault('lane_errors', {})[lane] = True
            self._summarize(state)
            state['last_error_stage'] = phase
            if self.leases.owns('collection-lease', owner, self.now()):
                save()
            return {'state': 'error', 'pages': pages}
        finally:
            self.leases.release('collection-lease', owner)

    @staticmethod
    def _part(date, page=1, **extra):
        return {'region': None, 'date': date, 'page': page, 'offset': 0, **extra}

    @staticmethod
    def _summarize(state):
        reasons = {}
        for values in [*state.get('partition_skipped', {}).values(), state.get('current_skipped', {})]:
            for reason, count in values.items():
                reasons[reason] = reasons.get(reason, 0)+count
        state.update(cycle_skipped=sum(reasons.values()), cycle_skipped_reasons=reasons,
                     last_error='collection_failed' if state.get('lane_errors') else '')


# Preserve imports in archived local verification scripts; the strategy is now a full walk.
LatestFirstMessageCollector = RecentWindowMessageCollector
