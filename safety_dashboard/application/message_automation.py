"""Validated automation settings and safe, read-only operator status."""
from __future__ import annotations
from dataclasses import dataclass
import datetime as dt
import os
from safety_dashboard.application.message_pipeline import AnalysisRunGate, MessageAnalysisQueue, UTC, moment
from safety_dashboard.application.message_feed_budget import OfficialRequestBudget
from safety_dashboard.application.message_spend_budget import MessageSpendBudget

@dataclass(frozen=True)
class MessageAutomationSettings:
    enabled: bool = False
    contract_verified: bool = False
    daily_limit: int = 20
    max_pages: int = 4
    catchup_days: int = 7
    interval_seconds: int = 900
    request_limit: int = 450
    scan_seconds: int = 120
    auto_max_age_hours: int = 24
    start_at: dt.datetime | None = None
    notification_preparation_enabled: bool = False
    latest_first_enabled: bool = False
    spend_budget_enabled: bool = False
    daily_budget_cents: int = 100
    monthly_budget_cents: int = 2000
    emergency_fallback_enabled: bool = False
    delivery_enabled: bool = False

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
        fast = flag('MESSAGE_COLLECTION_FAST_ENABLED')
        minutes = number('MESSAGE_COLLECTION_INTERVAL_MINUTES', 5 if fast else 15, 5, 60)
        if minutes not in ((5,) if fast else (15, 30, 60)):
            raise ValueError('MESSAGE_COLLECTION_INTERVAL_MINUTES: 최신 우선은 5분, 기존 수집은 15, 30, 60분 중 하나가 필요합니다.')
        fallback = flag('MESSAGE_EMERGENCY_FALLBACK_ENABLED')
        if fallback and not flag('MESSAGE_NOTIFICATION_PREPARATION_ENABLED'):
            raise ValueError('MESSAGE_EMERGENCY_FALLBACK_ENABLED: 알림 준비 활성화가 필요합니다.')
        delivery = flag('MESSAGE_DELIVERY_ENABLED')
        if delivery and not all((flag('MESSAGE_COLLECTION_ENABLED'), flag('MESSAGE_COLLECTION_CONTRACT_VERIFIED'),
                                 flag('MESSAGE_NOTIFICATION_PREPARATION_ENABLED'), fast, flag('MESSAGE_AI_SPEND_BUDGET_ENABLED'), fallback)):
            raise ValueError('MESSAGE_DELIVERY_ENABLED: 공식 수집·최신 우선·알림 준비·비용 제한·긴급 대체 설정이 필요합니다.')
        return cls(enabled=flag('MESSAGE_COLLECTION_ENABLED'), contract_verified=flag('MESSAGE_COLLECTION_CONTRACT_VERIFIED'),
                   notification_preparation_enabled=flag('MESSAGE_NOTIFICATION_PREPARATION_ENABLED'),
                   latest_first_enabled=fast, spend_budget_enabled=flag('MESSAGE_AI_SPEND_BUDGET_ENABLED'),
                   daily_budget_cents=number('MESSAGE_AI_DAILY_BUDGET_CENTS', 100, 1, 100_000),
                   monthly_budget_cents=number('MESSAGE_AI_MONTHLY_BUDGET_CENTS', 2000, 1, 1_000_000),
                   emergency_fallback_enabled=fallback,
                   delivery_enabled=delivery,
                   daily_limit=number('MESSAGE_ANALYSIS_DAILY_LIMIT', 20, 1, 100),
                   max_pages=number('MESSAGE_COLLECTION_MAX_PAGES', 4, 1, 4),
                   catchup_days=number('MESSAGE_COLLECTION_CATCHUP_DAYS', 7, 2, 30),
                   request_limit=number('MESSAGE_FEED_REQUEST_LIMIT', 450, 1, 450), interval_seconds=minutes*60, start_at=start)

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
            result.update(last_attempt_at=state.get('last_attempt_at'), last_success_at=state.get('last_success_at'), start_at=state.get('start_at'), queue=MessageAnalysisQueue(store).counts(), budget=AnalysisRunGate(store, settings.daily_limit, now=self.now).status(), remaining_partitions=len(state.get('work', [])), skipped_rows=state.get('cycle_skipped', 0), coverage_gap=bool(state.get('coverage_gap')),
                          skipped_reasons=state.get('cycle_skipped_reasons', {}), ignored_before_start=state.get('cycle_ignored_before_start', 0),
                          latest_first_enabled=settings.latest_first_enabled, last_latest_success_at=state.get('last_latest_success_at'),
                          last_backfill_success_at=state.get('last_backfill_success_at'),
                          feed_budget=OfficialRequestBudget(store,settings.request_limit,now=self.now,latest_reserve=289 if settings.latest_first_enabled else 0).status(),
                          spend_budget=MessageSpendBudget(store,daily_cents=settings.daily_budget_cents,monthly_cents=settings.monthly_budget_cents,now=self.now).status() if settings.spend_budget_enabled else {'enabled': False})
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
        if result['feed_budget']['remaining'] == 0:
            result.update(state='request_limit', detail='문자 조회 한도로 대기 중입니다. 남은 수집 작업을 보존하고 한도가 회복되면 이어갑니다.')
            return result
        if not state.get('last_attempt_at'):
            result.update(state='starting', detail='자동 수집 첫 실행을 기다리고 있습니다.')
            return result
        if (self.now() - moment(state['last_attempt_at'])).total_seconds() > settings.interval_seconds * 2 + 60:
            result.update(state='stale', detail='자동 수집 실행이 지연되고 있습니다. 마지막 정상 조회 시각을 확인해 주세요.')
        elif state.get('last_error'):
            result.update(state='error', detail='공식 문자 조회를 완료하지 못했습니다. 이전 기록과 대기 작업은 유지됩니다.')
        elif state.get('work') or state.get('latest_part') or state.get('cycle_skipped') or state.get('coverage_gap'):
            if state.get('work') or state.get('latest_part') or state.get('coverage_gap'):
                detail='일부 기간·페이지를 추가 확인 중입니다. 현재 목록이 전체 수집 결과는 아닙니다.'
            else:
                labels={'recipient_region':'수신지역 확인 필요','source_fields':'원문 필드 확인 필요','query_date':'발행 날짜 확인 필요','source_validation':'원문 형식 확인 필요'}
                reasons=state.get('cycle_skipped_reasons',{})
                counts=' · '.join(f'{label} {reasons[key]}회' for key,label in labels.items() if reasons.get(key))
                detail='조회는 끝났지만 일부 문자 항목을 확인하지 못했습니다.'+(' '+counts if counts else '')+' 같은 항목의 겹침 조회도 포함한 횟수이며, 이전 기록은 유지됩니다.'
            result.update(state='partial', detail=detail)
            if settings.latest_first_enabled and result['feed_budget']['background_remaining'] == 0 and state.get('work'):
                result['detail'] = '추가 페이지·과거 자료는 조회 몫이 회복될 때 이어갑니다. 최신 첫 페이지 확인을 우선하며 전체 수집 완료는 아닙니다.'
        elif not state.get('last_success_at'):
            result.update(state='starting', detail='첫 정상 조회 완료를 기다리고 있습니다.')
        else:
            result.update(state='live', detail='공식 API의 공개 문자를 주기적으로 수집하고 있습니다.')
        return result
