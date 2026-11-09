"""Reproduce preview-only durability checks using explicit fake models/stores."""
import copy
import datetime as dt
import json
from pathlib import Path
import sys
import uuid
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT))
from scripts.test_support import NetworkGuard

with NetworkGuard() as guard:
    from tests.test_message_notification_jobs import Fixture
    from tests.test_message_notification_store import NotificationStoreTests
    from safety_dashboard.application.message_records import AnalyzeRecord,RegisterMessage
    from safety_dashboard.application.message_notification_jobs import CONFIG_KEY
    checks=[]

    f=Fixture();record=f.analyzed();first=f.planner.prepare_record(record['id'])
    f.new_planner().run();again=f.new_planner().prepare_record(record['id'])
    assert first['job_id']==again['job_id'] and len(f.jobs())==1 and f.analyzer.analyze.call_count==1
    assert f.records.get(record['id'])['version']==record['version']
    checks.append({'case':'restart_and_duplicate','jobs':1,'new_model_calls_during_recovery':0,'human_version_changes':0})

    f=Fixture();record=f.analyzed()
    with patch.object(f.repo,'run_record',side_effect=RuntimeError('simulated interruption')):
        try:f.planner.prepare_record(record['id'])
        except RuntimeError:pass
    assert f.records.get(record['id'])['notification_dirty'] and not f.jobs()
    f.new_planner().run()
    assert len(f.jobs())==1 and f.analyzer.analyze.call_count==1
    checks.append({'case':'interruption_before_commit','dirty_before':True,'dirty_after':False,'jobs_after_recovery':1,'new_model_calls_during_recovery':0})

    f=Fixture();record=f.register();first=f.planner.prepare_record(record['id'])
    assert first['job_id'] is None
    record=f.records.analyze(record['id'],AnalyzeRecord(expected_version=record['version']))
    second=f.planner.prepare_record(record['id'])
    assert second['state']=='pending' and second['first_finalization']
    checks.append({'case':'provisional_then_analyzed','job_before_analysis':None,'job_state_after':'pending'})

    f=Fixture();record=f.analyzed();old=f.planner.prepare_record(record['id'])
    f.clock[0]+=dt.timedelta(minutes=1)
    correction=f.records.register_official({**f.message,'text':f.message['text']+' 안내를 정정합니다.'},'SN-stage2',f.clock[0].isoformat())['record']
    f.planner.prepare_record(correction['id'])
    correction=f.records.analyze(correction['id'],AnalyzeRecord(expected_version=correction['version']))
    newest=f.planner.prepare_record(correction['id'])
    assert old['job_id']!=newest['job_id'] and len(f.jobs())==2
    assert sum(j['state']=='pending' for j in f.jobs())==1
    checks.append({'case':'official_correction','old_state':'invalidated','new_state':'pending','jobs_for_distinct_source_versions':2})

    f=Fixture();record=f.analyzed();first=f.planner.prepare_record(record['id'])
    record=f.records.analyze(record['id'],AnalyzeRecord(expected_version=record['version']))
    second=f.planner.prepare_record(record['id'])
    assert second['job_id']==first['job_id'] and second['state']=='invalidated' and len(f.jobs())==1
    checks.append({'case':'same_source_reanalysis','state':'invalidated','new_job_created':False})

    for kind in ('manual','example'):
        f=Fixture()
        record=f.records.register_manual(RegisterMessage(registration_key=uuid.uuid4(),input_kind=kind,
            text=f.message['text'],source=f.message['source'],issued_at=f.message['issued_at'],recipient_regions=[]))['record']
        record=f.records.analyze(record['id'],AnalyzeRecord(expected_version=record['version']))
        f.planner.run()
        assert not f.jobs() and not f.records.get(record['id'])['notification_dirty']
        checks.append({'case':kind+'_never_auto_queued','jobs':0,'human_version_changes':0})

    f,client=NotificationStoreTests().firestore_fixture();record=f.analyzed()
    client.fail_notification_commit_once=True
    try:f.planner.prepare_record(record['id'])
    except RuntimeError:pass
    assert f.records.get(record['id'])['notification_dirty']
    assert not any('/notification-job-' in k for k in client.documents)
    f.new_planner().run()
    assert f.planner.read_record(record['id'])['state']=='pending' and f.analyzer.analyze.call_count==1
    checks.append({'case':'atomic_firestore_spy_abort','partial_jobs':0,'state_after_restart':'pending','new_model_calls_during_recovery':0})
    guard.assert_unused()

summary={'phase':'preview_only','checks':checks,'external_http_tcp_attempts':0,'real_model_http_calls':0,
         'real_messages_sent':0,'production_deployed':False,'firestore_mode':'transaction spy, not production IAM validation'}
Path(__file__).with_name('recovery-checks.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
print(json.dumps({'checks':len(checks),'external_http_tcp_attempts':0,'real_model_http_calls':0,'real_messages_sent':0}))
