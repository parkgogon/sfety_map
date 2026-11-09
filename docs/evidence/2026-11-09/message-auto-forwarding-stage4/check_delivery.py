"""Reproduce delivery boundaries using memory/Firestore spies and fake transports."""
import datetime as dt
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT))
from scripts.test_support import NetworkGuard

with NetworkGuard() as guard:
    from tests.test_message_delivery import DeliveryFixture,DeliveryTests
    from safety_dashboard.adapters.telegram import TelegramDeliveryResult
    checks=[]
    f=DeliveryFixture();record,jid=f.ready();before=f.records.store.history(record['id'],None,100)
    f.delivery.run();f.service().run()
    assert len(f.staff.calls)==1 and f.outbox(jid)['state']=='sent' and f.outbox(jid)['message_id']==1
    assert f.records.store.history(record['id'],None,100)==before and not f.repo.get(jid)['dispatch_enabled']
    assert '/control' not in f.repo.get(jid)['snapshot']['map_url']
    checks.append({'case':'confirmed_once_after_restart','fake_staff_requests':1,'receipt_id_saved':True,'human_record_changes':0,'preview_permission_escalated':False,'staff_link':'public_map'})

    f=DeliveryFixture(start=False);_,jid=f.ready();f.delivery.configure('start',None);f.delivery.run()
    assert not f.staff.calls and f.outbox(jid) is None
    checks.append({'case':'existing_preview_not_promoted','fake_staff_requests':0})

    f=DeliveryFixture();_,jid=f.ready();f.staff.results=[TelegramDeliveryResult('unknown',detail='outcome_unknown')]
    f.delivery.run();f.delivery.run();f.service().run()
    assert len(f.staff.calls)==1 and len(f.admin.calls)==1 and f.outbox(jid)['state']=='unknown'
    f.delivery.acknowledge(f.outbox(jid)['id'],'handled_separately')
    assert f.outbox(jid)['state']=='unknown'
    checks.append({'case':'unknown_is_not_resent','fake_staff_requests':1,'fake_admin_requests':1,'manual_resolution_does_not_claim_api_success':True})

    f=DeliveryFixture();_,jid=f.ready()
    f.staff.results=[TelegramDeliveryResult('rate_limited',retry_after=1,detail='provider_rate_limit')]*3
    for _ in range(3):f.delivery.run();f.clock[0]+=dt.timedelta(seconds=61)
    assert f.outbox(jid)['state']=='rejected' and len(f.staff.calls)==3
    checks.append({'case':'explicit_429_only','max_attempts':3,'state_after_exhaustion':'rejected'})

    f=DeliveryFixture();_,jid=f.ready()
    with patch.object(f.delivery,'_finish',side_effect=RuntimeError('simulated acknowledgement loss')):
        try:f.delivery.run()
        except Exception:pass
    assert f.outbox(jid)['state']=='sending'
    f.clock[0]+=dt.timedelta(minutes=6);f.delivery.run()
    assert f.outbox(jid)['state']=='unknown' and len(f.staff.calls)==1
    checks.append({'case':'lost_receipt_commit','state_after_recovery':'unknown','additional_staff_requests':0})

    for name,method in (
        ('source_or_catalog_change_blocks_request','test_source_or_basis_changed_before_request_prevents_transport'),
        ('concurrent_worker_claim','test_two_worker_instances_cannot_send_the_same_source_twice'),
        ('manual_reconsideration_only_before_first_attempt','test_manual_reconsideration_can_only_rearm_a_fresh_never_attempted_source'),
        ('firestore_transaction_abort','test_firestore_claim_commits_all_reads_before_writes_and_aborted_claim_cannot_send'),
        ('independent_admin_queue','test_admin_exception_is_not_held_behind_a_full_staff_batch')):
        getattr(DeliveryTests(),method)()
        checks.append({'case':name,'result':'passed'})
    guard.assert_unused()

report={'fixture_only':True,'checks':checks,'external_http_tcp_attempts':0,'real_model_http_calls':0,
        'real_messages_sent':0,'production_deployed':False,'actual_firestore_iam_verified':False,'actual_telegram_receipt_verified':False}
Path(__file__).with_name('delivery-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'checks':len(checks),'external_http_tcp_attempts':0,'real_messages_sent':0}))
