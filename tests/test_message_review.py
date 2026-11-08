import copy
import datetime as dt
import unittest
from unittest.mock import Mock

from fastapi.testclient import TestClient
from pydantic import ValidationError
from safety_dashboard.api.app import create_app
from safety_dashboard.admin.access import AdminAccessSettings, AdminAccessVerifier
from safety_dashboard.application.message_records import AnalyzeRecord, RecordConflict, SaveRecordNote
from safety_dashboard.application.message_review import (
    MessageReviewService, CompleteMessageReview, ReopenMessageReview, SaveMessageNotice, CopyMessageNotice, ReviewValidationError,
)
from safety_dashboard.application.message_spatial import SaveMessageReference, message_locations
from tests.test_message_records import registration, NOW
from tests import test_message_spatial as spatial_fixtures
from tests.test_message_spatial import D2, facility


class MessageReviewTests(unittest.TestCase):
    current = spatial_fixtures.SpatialTests.current
    reference = spatial_fixtures.SpatialTests.reference
    selection = spatial_fixtures.SpatialTests.selection

    def setUp(self):
        spatial_fixtures.SpatialTests.setUp(self)
        self.review = MessageReviewService(self.records, self.catalog)

    def request(self, outcome='facilities_selected', **overrides):
        record = self.current()
        excluded = [{'location_key': loc['key'], 'reason': '별도 확인할 장소로 남김'}
            for loc in message_locations(record) if loc['eligible'] and not record.get('spatial_references', {}).get(loc['key'], {}).get('selected')]
        return CompleteMessageReview(**{'expected_version': record['version'], 'outcome': outcome,
            'reason': '업무상 확인할 시설을 선정했음' if outcome == 'facilities_selected' else '예방 안내로 추가 대상 선정이 필요하지 않음',
            'follow_up_note': '정확한 발생 지점은 추가 확인 필요', 'excluded_locations': excluded if outcome == 'facilities_selected' else [], **overrides})

    def selected_record(self):
        self.reference()
        return self.svc.save_selection(self.record['id'], self.selection(['0']))

    def complete(self, **kwargs):
        return self.review.complete(self.record['id'], self.request(**kwargs))

    def test_complete_persists_grounded_snapshot_and_current_template_without_ai_or_private_metadata(self):
        self.selected_record(); rec = self.complete()
        self.assertEqual(rec['review_state'], 'completed')
        self.assertEqual(rec['review_completion']['selected_unique_count'], 1)
        self.assertEqual(rec['review_completion']['snapshot']['locations'][0]['selected'][0]['distance_m'], 0)
        self.assertTrue(self.review.detail(rec['id'])['draft_current'])
        self.assertIn('수동 입력 문자', rec['notice_draft']['text'])
        self.assertIn(self.current()['message']['text'], rec['notice_draft']['text'])
        self.assertIn('대피 목적지: 성서초등학교', rec['notice_draft']['text'])
        self.assertIn('미선정 장소: 중앙동 사거리', rec['notice_draft']['text'])
        self.assertIn('별도 확인', rec['notice_draft']['text'])
        self.assertNotIn('private-', str(rec['review_completion']))
        self.assertNotIn('private-', rec['notice_draft']['text'])
        self.assertEqual(self.analyzer.analyze.call_count, 1)

    def test_no_action_does_not_require_facility_lookup_if_no_reference_was_used(self):
        rec = self.complete(outcome='no_action', follow_up_note='')
        self.assertNotIn('질문의 해결 여부', rec['notice_draft']['text'])
        self.assertEqual(rec['review_completion']['selected_unique_count'], 0)
        self.catalog.assert_not_called()
        self.assertIn('추가 조치 없음', rec['notice_draft']['text'])
        self.assertIn('시설 안전', rec['notice_draft']['text'])
        with self.assertRaises(ValidationError): self.request('no_action', reason=' ')

    def test_cannot_complete_without_selection_or_no_action_while_selection_remains(self):
        with self.assertRaises(ReviewValidationError): self.complete()
        self.selected_record()
        with self.assertRaises(ReviewValidationError): self.complete(outcome='no_action')
        self.assertNotEqual(self.current()['review_state'], 'completed')

    def test_other_incident_locations_require_explicit_exclusion_reason(self):
        self.selected_record()
        for excluded in ([], [{'location_key':'0:0','reason':'잘못된 장소'}],
                         [{'location_key':'1:0','reason':'확인 중'},{'location_key':'1:0','reason':'중복'}]):
            with self.assertRaises(ReviewValidationError): self.complete(excluded_locations=excluded)
        rec = self.complete()
        self.assertEqual(rec['review_completion']['excluded_locations'], {'1:0':'별도 확인할 장소로 남김'})

    def test_same_facility_in_two_contexts_has_one_unique_count_and_two_reference_groups(self):
        self.selected_record()
        self.reference('1:0', {'mode':'manual','latitude':35.85,'longitude':128.5,'manual_source':'map'})
        self.svc.save_selection(self.record['id'], self.selection(['0'], key='1:0'))
        rec = self.complete()
        self.assertEqual(rec['review_completion']['selected_unique_count'], 1)
        self.assertEqual(sum(bool(l['selected']) for l in rec['review_completion']['snapshot']['locations']), 2)
        self.assertIn('중복 제외 1개소', rec['notice_draft']['text'])

    def test_catalog_change_blocks_completion_and_later_copy(self):
        self.selected_record()
        old_catalog = self.catalog.return_value
        self.catalog.return_value = D2, (facility('0',5000),)
        with self.assertRaises(RecordConflict): self.complete()
        self.catalog.return_value = old_catalog
        rec = self.complete(); version = rec['version']
        self.catalog.return_value = D2, old_catalog[1]
        detail = self.review.detail(rec['id'])
        self.assertFalse(detail['completion_current']); self.assertFalse(detail['draft_current'])
        with self.assertRaises(RecordConflict): self.review.copy_draft(rec['id'], CopyMessageNotice(expected_version=version,draft_revision=1))
        self.assertEqual(self.current()['version'], version)

    def test_completed_record_requires_reopen_before_note_analysis_reference_or_selection_edit(self):
        self.selected_record(); rec = self.complete()
        operations = [lambda:self.records.save_note(rec['id'],SaveRecordNote(expected_version=rec['version'],review_state='needs_confirmation',note='edit')),
            lambda:self.records.analyze(rec['id'],AnalyzeRecord(expected_version=rec['version'])),
            lambda:self.reference(), lambda:self.svc.save_selection(rec['id'],self.selection(['1']))]
        for operation in operations:
            with self.assertRaises(RecordConflict): operation()
        self.assertEqual(self.current()['version'],rec['version'])
        self.assertEqual(self.analyzer.analyze.call_count,1)

    def test_reopen_preserves_prior_completed_draft_in_history_and_requires_new_review(self):
        self.selected_record(); rec = self.complete(); old_draft = copy.deepcopy(rec['notice_draft'])
        reopened = self.review.reopen(rec['id'],ReopenMessageReview(expected_version=rec['version'],reason='확인 결과 보완'))
        self.assertEqual(reopened['review_state'],'needs_confirmation')
        self.assertIsNone(reopened['notice_draft']); self.assertIsNone(reopened['review_completion'])
        self.assertEqual(reopened['review_reopen_reason'],'확인 결과 보완')
        with self.assertRaises(RecordConflict): self.review.copy_draft(rec['id'],CopyMessageNotice(expected_version=reopened['version'],draft_revision=old_draft['revision']))
        self.assertTrue(any(v['record'].get('notice_draft')==old_draft for v in self.records.store.history(rec['id'],None,50)))
        again = self.complete()
        self.assertGreater(again['notice_draft']['revision'],old_draft['revision'])

    def test_additional_note_regenerates_a_versioned_draft_without_editing_source_or_required_labels(self):
        self.record = self.records.register_manual(registration(input_kind='example'))['record']
        self.record = self.records.analyze(self.record['id'],AnalyzeRecord(expected_version=1))
        rec = self.complete(outcome='no_action'); old = copy.deepcopy(rec)
        new = self.review.save_draft(rec['id'],SaveMessageNotice(expected_version=rec['version'],draft_revision=1,manager_note='추가 안내 첫 줄\n둘째 줄'))
        self.assertEqual(new['message'],old['message']); self.assertEqual(new['review_completion'],old['review_completion'])
        self.assertEqual(new['notice_draft']['revision'],2)
        self.assertIn('창작 예문 · 실제 재난/업무 실적 아님',new['notice_draft']['text'])
        self.assertIn('추가 안내 첫 줄\n둘째 줄',new['notice_draft']['text'])
        self.assertIn('실제 발송·수신 기록이 아닙니다',new['notice_draft']['text'])
        copied=self.review.copy_draft(new['id'],CopyMessageNotice(expected_version=new['version'],draft_revision=2))
        self.assertEqual(copied['text'],new['notice_draft']['text']);self.assertEqual(self.current()['version'],new['version'])

    def test_notice_copy_and_save_reject_stale_record_or_draft_versions_and_client_text_injection(self):
        self.selected_record(); rec = self.complete()
        for version,draft in ((rec['version']-1,1),(rec['version'],2)):
            with self.assertRaises(RecordConflict):self.review.copy_draft(rec['id'],CopyMessageNotice(expected_version=version,draft_revision=draft))
        with self.assertRaises(ValidationError): SaveMessageNotice(expected_version=1,draft_revision=1,manager_note='',text='임의 초안')
        with self.assertRaises(ValidationError): CompleteMessageReview(expected_version=1,outcome='no_action',reason='근거',snapshot={})

    def test_partial_release_and_active_segment_remain_distinct_in_notice(self):
        self.analyzer.analyze.return_value={'analysis':{'parts':[
            {'intent':'release','evidence':'가람교 15시 해제','starts_at':None,'ends_at':'2026-11-08T15:00:00+09:00','locations':[{'text':'가람교','role':'restricted_area','candidate_ids':[],'evidence':'가람교'}]},
            {'intent':'active_restriction','evidence':'푸른교 통제 유지','locations':[{'text':'푸른교','role':'restricted_area','candidate_ids':[],'evidence':'푸른교'}]},
        ],'questions':['푸른교 위치 확인'],'summary':'부분 해제'},'candidates':[]}
        self.records.analyze(self.record['id'],AnalyzeRecord(expected_version=self.current()['version']))
        text=self.complete(outcome='no_action')['notice_draft']['text']
        self.assertIn('해제: 가람교',text);self.assertIn('통제 유지: 푸른교',text)
        self.assertIn('종료/해제: 2026-11-08 15:00',text);self.assertIn('분석 시 제시된 질문: 푸른교 위치 확인',text)

    def test_source_update_automatically_invalidates_completion_and_draft(self):
        original=self.current()['message']
        self.record=self.records.register_official(original,'official-review-1',NOW.isoformat())['record']
        self.record=self.records.analyze(self.record['id'],AnalyzeRecord(expected_version=1))
        self.selected_record();rec=self.complete();old_draft=rec['notice_draft']
        updated=self.records.register_official({**original,'text':'정정된 재난문자입니다. 사고 위치가 변경되었습니다.'},'official-review-1',(NOW+dt.timedelta(minutes=1)).isoformat())['record']
        self.assertEqual(updated['review_state'],'needs_confirmation');self.assertIsNone(updated['notice_draft'])
        self.assertIsNone(updated['review_completion'])
        self.assertTrue(any(v['record'].get('notice_draft')==old_draft for v in self.records.store.history(rec['id'],None,50)))

    def test_identical_official_observation_does_not_invalidate_completed_basis(self):
        original=self.current()['message'];self.record=self.records.register_official(original,'official-review-1',NOW.isoformat())['record']
        self.records.analyze(self.record['id'],AnalyzeRecord(expected_version=1));self.selected_record();self.complete()
        observed=self.records.register_official(original,'official-review-1',(NOW+dt.timedelta(minutes=1)).isoformat())['record']
        self.assertTrue(self.review.detail(observed['id'])['draft_current'])

    def test_storage_failure_does_not_claim_completed_review(self):
        self.selected_record();before=self.current()
        commit=self.records.store.commit;self.records.store.commit=Mock(side_effect=RuntimeError('private-storage-token'))
        with self.assertRaises(RuntimeError):self.complete()
        self.records.store.commit=commit
        self.assertEqual(self.current(),before)


class MessageReviewRouteTests(unittest.TestCase):
    current=spatial_fixtures.SpatialTests.current
    reference=spatial_fixtures.SpatialTests.reference
    selection=spatial_fixtures.SpatialTests.selection

    def setUp(self):
        spatial_fixtures.SpatialTests.setUp(self)
        self.client=TestClient(create_app(admin_access_service=AdminAccessVerifier(AdminAccessSettings(password='test-pass')),
            message_record_service=self.records,message_spatial_service=self.svc))
        self.base='/internal/v1/message-records/'+self.record['id']

    def login(self):self.assertEqual(self.client.post('/internal/v1/admin/access',json={'password':'test-pass'}).status_code,200)

    def test_all_review_routes_require_admin_and_no_provider_or_store_calls(self):
        self.records.store_factory=Mock(side_effect=AssertionError('unauthorized'));self.records._store=None
        for method,path,body in [('GET','/review',None),('POST','/complete',{'expected_version':1,'outcome':'no_action','reason':'test'}),
                ('POST','/reopen',{'expected_version':1,'reason':'test'}),('POST','/notice',{'expected_version':1,'draft_revision':1}),('POST','/notice-copy',{'expected_version':1,'draft_revision':1})]:
            response=self.client.request(method,self.base+path,json=body)
            self.assertEqual(response.status_code,403);self.assertEqual(response.headers['cache-control'],'private, no-store')
        self.records.store_factory.assert_not_called();self.catalog.assert_not_called()

    def test_complete_copy_reopen_end_to_end_and_no_fake_delivery_event(self):
        self.login()
        response=self.client.post(self.base+'/complete',json={'expected_version':self.current()['version'],'outcome':'no_action','reason':'예방 안내 검토'})
        self.assertEqual(response.status_code,200,response.text);rec=response.json()
        copy_response=self.client.post(self.base+'/notice-copy',json={'expected_version':rec['version'],'draft_revision':1})
        self.assertEqual(copy_response.status_code,200);self.assertIn('예방 안내 검토',copy_response.json()['text'])
        self.assertEqual(self.current()['version'],rec['version'])
        self.assertEqual(self.client.post(self.base+'/reopen',json={'expected_version':rec['version'],'reason':''}).status_code,422)
        response=self.client.post(self.base+'/reopen',json={'expected_version':rec['version'],'reason':'검토 보완'})
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['review_state'],'needs_confirmation')
        self.assertEqual(self.client.post(self.base+'/notice-copy',json={'expected_version':response.json()['version'],'draft_revision':1}).status_code,409)

    def test_conflict_and_storage_errors_are_not_success_and_do_not_leak_tokens(self):
        self.login()
        self.assertEqual(self.client.post(self.base+'/complete',json={'expected_version':1,'outcome':'no_action','reason':'검토'}).status_code,409)
        self.records.store.commit=Mock(side_effect=RuntimeError('private-storage-token'))
        response=self.client.post(self.base+'/complete',json={'expected_version':self.current()['version'],'outcome':'no_action','reason':'검토'})
        self.assertEqual(response.status_code,503);self.assertNotIn('private-storage-token',response.text)
