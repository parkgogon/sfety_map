"""Validated automation settings and safe, read-only operator status."""
from __future__ import annotations
from dataclasses import dataclass
import datetime as dt
import os
from safety_dashboard.application.message_pipeline import AnalysisRunGate, MessageAnalysisQueue, UTC, moment

@dataclass(frozen=True)
class MessageAutomationSettings:
    enabled: bool = False
    contract_verified: bool = False
    daily_limit: int = 20
    max_pages: int = 20
    catchup_days: int = 7
    interval_seconds: int = 300
    scan_seconds: int = 120
    auto_max_age_hours: int = 24
    start_at: dt.datetime | None = None

    @classmethod
    def from_environment(cls, env=None):
        env = os.environ if env is None else env

        def flag(name):
            value = env.get(name, 'false').strip()
            if value not in {'true', 'false'}:
                raise ValueError(name + ': true 또는 false가 필요합니다.')
            return value == 'true'

        def number(name, default, minimum, maximum):
            value = env.get(name, str(default)).strip()
            if not value.isascii() or not value.isdigit() or (not minimum <= int(value) <= maximum):
                raise ValueError(name + ': 허용 범위의 정수가 필요합니다.')
            return int(value)
        raw = env.get('MESSAGE_COLLECTION_START_AT', '').strip()
        start = None
        if raw:
            try:
                start = dt.datetime.fromisoformat(raw)
                if start.tzinfo is None:
                    raise ValueError()
            except ValueError:
                raise ValueError('MESSAGE_COLLECTION_START_AT: 시간대가 있는 ISO 시각이 필요합니다.') from None
        return cls(enabled=flag('MESSAGE_COLLECTION_ENABLED'), contract_verified=flag('MESSAGE_COLLECTION_CONTRACT_VERIFIED'), daily_limit=number('MESSAGE_ANALYSIS_DAILY_LIMIT', 20, 1, 100), max_pages=number('MESSAGE_COLLECTION_MAX_PAGES', 20, 1, 50), catchup_days=number('MESSAGE_COLLECTION_CATCHUP_DAYS', 7, 2, 30), start_at=start)

class MessageAutomationStatus:

    def __init__(self, settings, store_factory, feed_configured, *, now=lambda: dt.datetime.now(UTC)):
        self.settings, self.store_factory, self.feed_configured, self.now = (settings, store_factory, feed_configured, now)

    def read(self):
        settings = self.settings
        result = {'auto_collection_enabled': settings.enabled, 'feed_configured': self.feed_configured, 'interval_seconds': settings.interval_seconds, 'state': 'disabled', 'detail': '공식 문자 자동 수집이 꺼져 있습니다. 직접 입력으로 검토할 수 있습니다.', 'last_attempt_at': None, 'last_success_at': None, 'start_at': None, 'queue': None, 'budget': {'limit': settings.daily_limit, 'attempts': None, 'remaining': None, 'active': False}}
        if not self.store_factory:
            if settings.enabled:
                result.update(state='store_unavailable', detail='자동 수집 저장소가 연결되지 않았습니다.')
            return result
        try:
            store = self.store_factory()
            state = store.get('collection-state') or {}
            result.update(last_attempt_at=state.get('last_attempt_at'), last_success_at=state.get('last_success_at'), start_at=state.get('start_at'), queue=MessageAnalysisQueue(store).counts(), budget=AnalysisRunGate(store, settings.daily_limit, now=self.now).status(), remaining_partitions=len(state.get('work', [])), skipped_rows=state.get('cycle_skipped', 0), coverage_gap=bool(state.get('coverage_gap')))
        except Exception:
            result.update(state='store_unavailable', detail='수집·분석 상태를 조회하지 못했습니다. 저장된 검토 기록은 유지됩니다.')
            return result
        if not settings.enabled:
            return result
        if not self.feed_configured:
            result.update(state='needs_key', detail='공식 재난문자 API 키 연결이 필요합니다.')
            return result
        if not settings.contract_verified:
            result.update(state='needs_verification', detail='공식 API 응답·조회 범위를 확인한 뒤 자동 수집을 활성화해 주세요.')
            return result
        if not state.get('last_attempt_at'):
            result.update(state='starting', detail='자동 수집 첫 실행을 기다리고 있습니다.')
            return result
        if (self.now() - moment(state['last_attempt_at'])).total_seconds() > settings.interval_seconds * 2 + 60:
            result.update(state='stale', detail='자동 수집 실행이 지연되고 있습니다. 마지막 정상 조회 시각을 확인해 주세요.')
        elif state.get('last_error'):
            result.update(state='error', detail='공식 문자 조회를 완료하지 못했습니다. 이전 기록과 대기 작업은 유지됩니다.')
        elif state.get('work') or state.get('cycle_skipped') or state.get('coverage_gap'):
            result.update(state='partial', detail='일부 기간·페이지를 추가 확인 중입니다. 현재 목록이 전체 수집 결과는 아닙니다.')
        elif not state.get('last_success_at'):
            result.update(state='starting', detail='첫 정상 조회 완료를 기다리고 있습니다.')
        else:
            result.update(state='live', detail='공식 API의 공개 문자를 주기적으로 수집하고 있습니다.')
        return result
