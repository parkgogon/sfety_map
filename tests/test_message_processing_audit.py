import copy
import datetime as dt
import json
import unittest
from types import SimpleNamespace

from scripts.audit_message_processing import audit, digest, receipt, safe_text, screenshot_case, probe_screenshot_source

NOW=dt.datetime.fromisoformat('2026-11-18T09:00:00+09:00')


class Reader:
    def __init__(self):
        self.records=[];self.values={};self.history_rows=[];self.incidents=[]
    def latest_records(self,limit):return copy.deepcopy(self.records[:limit])
    def pipeline(self,keys):return {k:copy.deepcopy(self.values[k]) for k in keys if k in self.values}
    def history(self,prefix,limit):return copy.deepcopy((self.history_rows if prefix=='MH|' else self.incidents)[:limit])


def record(origin='official'):
    return {'id':'official-'+'a'*64,'origin':origin,'source_revision':2,'content_hash':'b'*64,'created_at':NOW.isoformat(),
        'analysis_state':'completed','analysis_revision':1,'analysis_source_revision':2,
        'message':{'issued_at':NOW.isoformat(),'text':'대구 화재 private-original 010-1234-5678','recipient_regions':['대구광역시']},
        'analysis':{'analysis':{'summary':'대구 화재 안내, 연락처 010-1234-5678',
            'notification_assessment':{'need':'notify','relevance':'nearby','reason':'주변 시설 참고'},'parts':[]}}}


class MessageProcessingAuditTests(unittest.TestCase):
    def test_source_probe_is_bounded_and_never_exports_original_or_contacts(self):
        calls=[]
        row=SimpleNamespace(content='상주시 지진 규모 3.7 private-original 010-1234-5678',
            created_at=dt.datetime.fromisoformat('2026-11-17T23:10:00+09:00'), regions=('경상북도 상주시',))
        def fetch(*args):
            calls.append(args)
            return {'messages':[row], 'skipped':0, 'has_more':True}
        result=probe_screenshot_source(fetch=fetch, validate=lambda _:None, scope=lambda _:True)
        self.assertEqual(len(calls),3)
        self.assertEqual(result['api_calls'],3)
        self.assertFalse(result['source_scan_complete'])
        self.assertEqual(result['production_documents_written'],0)
        for private in ('private-original','010-1234-5678'):
            self.assertNotIn(private,json.dumps(result,ensure_ascii=False))

    def test_screenshot_cases_are_separate_and_not_inferred_from_recipient_city(self):
        def candidate(text, day):
            value=record();value['message'].update(text=text,issued_at=day+'T23:10:00+09:00')
            return value
        self.assertEqual(screenshot_case(candidate('대구시 범물동 613 농막 화재 발생', '2026-11-10')), 'beommul_fire')
        self.assertEqual(screenshot_case(candidate('경북 상주시 북서쪽 22km 지역 규모 3.7 지진발생', '2026-11-17')), 'sangju_earthquake_initial')
        self.assertEqual(screenshot_case(candidate('상주시 규모 3.7 지진은 상세분석을 통해 규모 3.6로 조정됨', '2026-11-17')), 'sangju_earthquake_correction')
        self.assertIsNone(screenshot_case(candidate('경북 상주시 화재', '2026-11-17')))
        self.assertIsNone(screenshot_case(candidate('상주 지진 규모 3.7', '2026-11-16')))

    def test_missing_screenshot_case_is_reported_without_claiming_source_feed_absence(self):
        r=Reader();r.records=[record()]
        result=audit(r,now=NOW)
        self.assertEqual(result['screenshot_cases']['sangju_earthquake_initial']['matches_in_scanned_records'],0)
        self.assertEqual(result['screenshot_cases']['beommul_fire']['record_ids'],[])
        self.assertFalse(result['scan_limit_reached'])

    def test_audit_only_reads_and_excludes_manual_examples_original_text_and_contacts(self):
        r=Reader();r.records=[record(),{**record('example'),'id':'manual-private'}]
        before=copy.deepcopy(r.__dict__);result=audit(r,now=NOW)
        self.assertEqual(r.__dict__,before)
        self.assertEqual(result['records_returned'],1)
        self.assertEqual(result['production_documents_written'],0)
        encoded=json.dumps(result,ensure_ascii=False)
        for private in ('private-original','010-1234-5678','manual-private'):self.assertNotIn(private,encoded)

    def test_old_version_receipt_does_not_become_current_version_delivery(self):
        r=Reader();value=record();r.records=[value]
        head='notification-head-'+digest(value['id'])
        r.values[head]={'decision_id':'decision-current','job_id':'job-current','state':'pending'}
        r.values['decision-current']={'scope':'eligible','snapshot':{'decision':'notify_ready','reason':'verified'}}
        r.history_rows=[{'record_id':value['id'],'source_revision':1,'destination':'staff_group','state':'sent','message_id':42}]
        result=audit(r,now=NOW)['records'][0]
        self.assertIsNone(result['current_delivery'])
        self.assertEqual(result['delivery_history'][0]['source_revision'],1)
        self.assertEqual(result['confirmed_staff_receipts_in_scanned_history'],1)
        self.assertEqual(result['source_revision'],2)

    def test_prepared_and_unknown_are_not_confirmed_receipts(self):
        for state in ('pending','sending','unknown','waiting','rejected'):
            self.assertFalse(receipt({'state':state,'message_id':42})['confirmed_api_receipt'])
        self.assertFalse(receipt({'state':'sent','message_id':0})['confirmed_api_receipt'])
        self.assertTrue(receipt({'state':'sent','message_id':42})['confirmed_api_receipt'])

    def test_current_outbox_receipt_and_server_record_only_remain_separate(self):
        r=Reader();value=record();r.records=[value]
        r.values['notification-head-'+digest(value['id'])]={'decision_id':'decision','job_id':'job','state':'pending'}
        r.values['decision']={'snapshot':{'decision':'record_only','reason':'일반 예방'}}
        r.values['message-delivery-'+digest('job')]={'state':'unknown','attempts':1}
        result=audit(r,now=NOW)['records'][0]
        self.assertEqual(result['server_decision'],'record_only')
        self.assertEqual(result['current_delivery']['state'],'unknown')
        self.assertFalse(result['current_delivery']['confirmed_api_receipt'])

    def test_sanitizer_removes_secret_url_and_phone(self):
        result=safe_text('010-1234-5678 https://example.test/?token=private sk-proj-'+'a'*30,300)
        for private in ('010-1234','token=private','a'*30):self.assertNotIn(private,result)
