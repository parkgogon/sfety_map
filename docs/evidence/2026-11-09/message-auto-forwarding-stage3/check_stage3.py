"""Reproduce collection/cost/fallback boundaries with synthetic records and no network."""
import datetime as dt
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT))
from scripts.test_support import NetworkGuard

with NetworkGuard() as guard:
    from tests.test_message_collection_latest import LatestCollectionTests, NOW
    from tests.test_message_notification_fallback import FallbackFixture, TEXT
    from safety_dashboard.application.message_pipeline import MemoryPipelineStore
    from safety_dashboard.application.message_spend_budget import MessageSpendBudget, MODEL, SpendBudgetLimit

    checks=[]
    f=LatestCollectionTests();f.setUp()
    for _ in range(161):f.budget.reserve()
    result=f.collect()
    assert result['state']=='request_limit' and f.feed.calls==[(NOW.date(),1,'latest')]
    assert f.store.get('collection-state')['work']
    checks.append({'case':'latest_survives_background_exhaustion','latest_pages':1,'background_pages':0,'backlog_preserved':True})

    f=LatestCollectionTests();f.setUp();f.test_one_page_today_and_yesterday_are_312_requests_per_24_hours()
    checks.append({'case':'one_page_24h_simulation','latest_requests':288,'history_requests':24,'total_requests':312})

    store=MemoryPipelineStore();budget=MessageSpendBudget(store,daily_cents=32,now=lambda:NOW)
    call=budget.reserve(MODEL)
    try:budget.reserve(MODEL)
    except SpendBudgetLimit:pass
    else:raise AssertionError('unknown reservation must block the next call')
    assert budget.status()['daily']['reserved_usd']==.318
    checks.append({'case':'unknown_response_keeps_reserve','reserved_usd':.318,'next_call':'blocked_before_http'})
    budget.settle(call,{'input_tokens':1000,'output_tokens':100,'input_tokens_details':{'cached_tokens':200}})
    assert budget.status()['daily']['reserved_usd']==0
    assert budget.status()['daily']['settled_usd']==.001065
    checks.append({'case':'actual_cached_token_settlement','input_tokens':1000,'cached_input_tokens':200,'output_tokens':100,'usd':.001065})

    f=FallbackFixture();record=f.register();f.planner.prepare_record(record['id'])
    assert not f.jobs() and not f.records.get(record['id'])['notification_dirty']
    f.reason[0]='ai_daily_limit';f.planner.run()
    assert len(f.jobs())==1 and TEXT in f.jobs()[0]['snapshot']['preview_text']
    assert not f.jobs()[0]['snapshot']['facilities'] and not f.jobs()[0]['dispatch_enabled']
    checks.append({'case':'clean_waiting_record_rechecked_on_quota_exhaustion','jobs':1,'whole_original_preserved':True,'invented_facilities':0})
    f.reason[0]=None
    assert f.planner.validate_pending(f.jobs()[0]['id'])['state']=='pending'
    assert not f.planner.auto_analysis_needed(f.records.get(record['id']))
    checks.append({'case':'quota_recovery_reuses_fallback','state':'pending','automatic_paid_reanalysis':False})
    f.clock[0]+=dt.timedelta(hours=1)
    assert f.planner.validate_pending(f.jobs()[0]['id'])['state']=='invalidated'
    checks.append({'case':'fallback_freshness_expiry','state':'invalidated','new_jobs':0})

    f=FallbackFixture();f.reason[0]='ai_spend_limit'
    record=f.register(message={**f.message,'text':'대구 전역에 폭염이 예상됩니다. 건강관리에 유의하세요.'})
    for _ in range(4):f.planner.prepare_record(record['id'])
    incidents=[v for v in f.pipeline.values.values() if v.get('queue_key','').startswith('NE|')]
    assert not f.jobs() and len(incidents)==1 and incidents[0]['source_count']==1
    checks.append({'case':'nonemergency_incident_deduplication','staff_jobs':0,'admin_incidents':1,'source_count':1})
    guard.assert_unused()

report={'phase':'preview_only','checks':checks,'external_http_tcp_attempts':0,'real_model_http_calls':0,
        'real_messages_sent':0,'production_deployed':False,'actual_model_quality_evaluated':False}
Path(__file__).with_name('stage3-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'checks':len(checks),'external_http_tcp_attempts':0,'real_model_http_calls':0,'real_messages_sent':0}))
