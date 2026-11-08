import copy
import unittest
from unittest.mock import Mock

from pydantic import ValidationError

from safety_dashboard.application.message_records import AnalyzeRecord, RecordConflict, SaveRecordNote, MessageSource
from safety_dashboard.application.message_preparation import (
    MessagePreparationService, PrepareMessageReview, ApprovePreparedReview,
)
from safety_dashboard.application.message_review import MessageReviewService, CopyMessageNotice, ReviewValidationError
from tests.test_message_records import make_service, registration
from tests.test_message_spatial import D1, D2, facility, result


class PreparationTests(unittest.TestCase):
    def setUp(self):
        output = result()
        output['analysis']['parts'] = output['analysis']['parts'][:1]
        output['candidates'][0]['place_kind'] = 'other'
        self.analyzer = Mock(); self.analyzer.analyze.return_value = output
        self.records = make_service(self.analyzer)
        record = self.records.register_manual(registration())['record']
        self.record = self.records.analyze(record['id'], AnalyzeRecord(expected_version=record['version']))
        self.catalog = Mock(return_value=(D1, (facility('near'), facility('far', 8000))))
        self.review = MessageReviewService(self.records, self.catalog)
        self.service = MessagePreparationService(self.review)

    def current(self):return self.records.get(self.record['id'])

    def request(self, **kwargs):return PrepareMessageReview(expected_version=self.current()['version'], **kwargs)

    def preview(self, request=None):return self.service.prepare(self.record['id'], request or self.request())

    def approve(self, request=None, preview=None):
        request = request or self.request()
        preview = preview or self.preview(request)
        return self.service.approve(self.record['id'], ApprovePreparedReview(**request.model_dump(), proposal_hash=preview['proposal_hash'], confirmed=True))

    def test_preview_has_grounded_defaults_without_human_confirmation_writes_or_ai_calls(self):
        before = self.current(); preview = self.preview()
        self.assertTrue(preview['ready']);self.assertEqual(preview['selected_count'], 1)
        self.assertEqual(preview['locations'][0]['selected'][0]['id'], 'near')
        self.assertIn('담당자 검토 전', preview['notice_preview'])
        self.assertNotIn('private-', str(preview))
        self.assertEqual(self.current(), before);self.assertEqual(self.analyzer.analyze.call_count, 1)
        self.assertFalse(self.current()['spatial_references'])

    def test_approve_commits_reference_selection_completion_and_brief_draft_in_one_version(self):
        before = self.current(); request = self.request(); preview = self.preview(request)
        saved = self.approve(request, preview)
        self.assertEqual(saved['version'], before['version']+1)
        self.assertEqual(saved['review_completion']['selected_unique_count'], 1)
        self.assertTrue(saved['spatial_references']['0:0']['confirmed_at'])
        self.assertEqual(saved['notice_draft']['format'], 'brief-v1')
        self.assertIn('near', str(saved['review_preparation']['recommendations']))
        self.assertEqual(self.approve(request, preview), saved)
        self.assertEqual(self.current()['version'], saved['version'])
        copied = self.review.copy_draft(saved['id'], CopyMessageNotice(expected_version=saved['version'], draft_revision=saved['notice_draft']['revision']))
        self.assertEqual(copied['text'], saved['notice_draft']['text'])

    def test_changed_facility_catalog_between_preview_and_approve_is_rejected_without_partial_save(self):
        request = self.request(); preview = self.preview(request); before = self.current()
        self.catalog.return_value = D2, self.catalog.return_value[1]
        with self.assertRaises(RecordConflict):self.approve(request, preview)
        self.assertEqual(self.current(), before)

    def test_record_version_and_changed_request_cannot_approve_an_old_preview(self):
        request = self.request(); preview = self.preview(request)
        with self.assertRaises(RecordConflict):self.approve(self.request(manager_note='변경한 안내'), preview)
        self.records.save_note(self.record['id'], SaveRecordNote(expected_version=request.expected_version, note='새 메모',review_state='unreviewed'))
        with self.assertRaises(RecordConflict):self.approve(request, preview)
        self.assertIsNone(self.current()['review_completion'])

    def test_representative_or_out_of_scope_point_requires_explicit_acknowledgment(self):
        output = copy.deepcopy(self.analyzer.analyze.return_value)
        output['candidates'][0]['place_kind'] = 'industrial_complex'
        self.analyzer.analyze.return_value = output
        self.record = self.records.analyze(self.record['id'], AnalyzeRecord(expected_version=self.current()['version']))
        self.assertFalse(self.preview()['ready'])
        with self.assertRaises(ReviewValidationError):self.approve()
        req = self.request(choices=[{'location_key':'0:0','reference_acknowledged':True}])
        self.assertTrue(self.preview(req)['ready']);self.assertEqual(self.approve(req)['review_state'],'completed')

    def test_destination_candidate_and_fabricated_or_duplicate_facilities_are_rejected(self):
        for choice in [{'location_key':'0:0','point':{'mode':'candidate','candidate_id':'P2'}},
                       {'location_key':'0:0','facilities':[{'facility_id':'invented'}]},
                       {'location_key':'0:0','facilities':[{'facility_id':'near'},{'facility_id':'near'}]}]:
            with self.subTest(choice=choice),self.assertRaises(ReviewValidationError):self.preview(self.request(choices=[choice]))
        with self.assertRaises(ValidationError):self.request(choices=[{'location_key':'0:0','point':{'mode':'manual','latitude':float('nan'),'longitude':128}}])

    def test_outside_facility_requires_its_reason_and_is_recomputed_by_server(self):
        req = self.request(choices=[{'location_key':'0:0','facilities':[{'facility_id':'far'}]}])
        self.assertFalse(self.preview(req)['ready'])
        req = self.request(choices=[{'location_key':'0:0','facilities':[{'facility_id':'far','reason':'현장 업무 관련'}]}])
        saved = self.approve(req)
        row = saved['spatial_references']['0:0']['selected'][0]
        self.assertFalse(row['within_radius']);self.assertAlmostEqual(row['distance_m'],8000,delta=2)

    def test_unresolved_other_location_needs_a_choice_but_exclusion_does_not_invent_coordinates(self):
        self.analyzer.analyze.return_value = result()
        self.record = self.records.analyze(self.record['id'], AnalyzeRecord(expected_version=self.current()['version']))
        self.assertFalse(self.preview()['ready'])
        req = self.request(choices=[{'location_key':'1:0','excluded_reason':'outside_scope'}])
        saved = self.approve(req)
        self.assertNotIn('1:0', saved['spatial_references'])
        self.assertIn('1:0', saved['review_completion']['excluded_locations'])

    def test_prevention_no_action_is_only_completed_by_explicit_approval(self):
        output = result();output['analysis']['parts'] = [{'intent':'prevention','locations':[]}]
        self.analyzer.analyze.return_value = output
        self.record = self.records.analyze(self.record['id'], AnalyzeRecord(expected_version=self.current()['version']))
        preview = self.preview();self.assertTrue(preview['ready']);self.assertEqual(preview['outcome'],'no_action')
        self.assertNotEqual(self.current()['review_state'],'completed')
        self.assertEqual(self.approve()['review_completion']['outcome'],'no_action')

    def test_storage_failure_leaves_reference_selection_and_completion_untouched(self):
        request=self.request();preview=self.preview(request);before=self.current()
        original=self.records.store.commit;self.records.store.commit=Mock(side_effect=RuntimeError('fake store unavailable'))
        try:
            with self.assertRaises(RuntimeError):self.approve(request, preview)
            self.assertEqual(self.current(),before)
        finally:self.records.store.commit=original

    def test_missing_publication_time_stays_unknown_instead_of_becoming_registration_time(self):
        payload = registration().model_dump();payload['issued_at']=None
        record = self.records.register_manual(type(registration())(**payload))['record']
        self.assertIsNone(record['message']['issued_at']);self.assertIsNotNone(record['created_at'])
        self.assertIsNone(MessageSource(**record['message']).canonical()['issued_at'])

    def test_hold_preserves_unapproved_edits_without_creating_confirmation_and_can_resume(self):
        req=self.request(choices=[{'location_key':'0:0','radius_km':1}],manager_note='확인 대기')
        saved=self.service.hold(self.record['id'],req)
        self.assertEqual(saved['review_state'],'needs_confirmation')
        self.assertFalse(saved['spatial_references']);self.assertIsNone(saved['review_completion'])
        resume=PrepareMessageReview(**{**saved['review_working_copy']['input'],'expected_version':saved['version']})
        self.assertEqual(self.approve(resume)['review_state'],'completed')

    def test_prevention_draft_also_rejects_copy_after_catalog_changes(self):
        output=result();output['analysis']['parts']=[{'intent':'advisory','locations':[]}]
        self.analyzer.analyze.return_value=output
        self.record=self.records.analyze(self.record['id'],AnalyzeRecord(expected_version=self.current()['version']))
        saved=self.approve();self.catalog.return_value=D2,self.catalog.return_value[1]
        with self.assertRaises(RecordConflict):self.review.copy_draft(saved['id'],CopyMessageNotice(expected_version=saved['version'],draft_revision=saved['notice_draft']['revision']))

    def test_idempotent_replay_cannot_silently_accept_a_different_payload(self):
        req=self.request();preview=self.preview(req);self.approve(req,preview)
        changed=PrepareMessageReview(**{**req.model_dump(),'manager_note':'다른 내용'})
        with self.assertRaises(RecordConflict):self.approve(changed,preview)

    def test_followup_dependency_change_invalidates_preview_even_without_parent_version_change(self):
        record=self.current();record['relation_epoch']=1
        self.records.store.commit(record,record['version'],'test')
        context=Mock(return_value={'links':[],'fingerprint':'before'})
        self.review.related_context=context
        req=self.request();preview=self.preview(req)
        context.return_value={'links':[],'fingerprint':'after'}
        with self.assertRaises(RecordConflict):self.approve(req,preview)

    def test_missing_issue_time_cannot_generate_a_guessed_absolute_time(self):
        from safety_dashboard.application.message_analysis import MessageAnalysisInput,MessageAnalysisService,AnalysisDraft,DraftEvidenceError
        request=MessageAnalysisInput(text='내일 오전부터 도로 통제 안내입니다.',source='공개 입력',input_kind='manual',reference_radius_km=3)
        draft=AnalysisDraft(summary='예정 통제',questions=['발행 시각 확인 필요'],parts=[{'intent':'scheduled_restriction','description':'예정 통제','evidence':request.text,'time_text':'내일 오전','starts_at':'2026-11-09T09:00:00+09:00','ends_at':None,'locations':[]}])
        with self.assertRaises(DraftEvidenceError):MessageAnalysisService._validate(draft,request,{}, {})

    def test_original_recommendation_is_preserved_when_user_selects_other_facilities(self):
        req=self.request(choices=[{'location_key':'0:0','facilities':[{'facility_id':'far','reason':'업무 관련'}]}])
        saved=self.approve(req)
        self.assertEqual(saved['review_preparation']['recommendations'][0]['facility_ids'],['near'])
        self.assertEqual(saved['spatial_references']['0:0']['selected'][0]['id'],'far')

    def test_followup_change_during_final_validation_does_not_leave_a_partial_review(self):
        record=self.current();record['relation_epoch']=1
        self.records.store.commit(record,record['version'],'test')
        self.review.related_context=Mock(return_value={'links':[],'fingerprint':'before'})
        req=self.request();preview=self.preview(req);before=self.current()
        self.review.related_context.side_effect=[{'links':[],'fingerprint':'before'},{'links':[],'fingerprint':'after'}]
        with self.assertRaises(RecordConflict):self.approve(req,preview)
        self.assertEqual(self.current(),before)

    def test_removed_facility_does_not_make_reopened_review_impossible_to_edit(self):
        from safety_dashboard.application.message_review import ReopenMessageReview
        saved=self.approve()
        self.review.reopen(saved['id'],ReopenMessageReview(expected_version=saved['version'],reason='자료 변경 확인'))
        self.catalog.return_value=D2,(facility('new'),)
        preview=self.preview()
        self.assertFalse(preview['ready']);self.assertEqual(preview['locations'][0]['removed_facilities'],[{'id':'near','name':'시설 near'}])
        req=self.request(choices=[{'location_key':'0:0','reference_acknowledged':True,'facilities':[{'facility_id':'new'}]}])
        self.assertEqual(self.approve(req)['spatial_references']['0:0']['selected'][0]['id'],'new')


class PreparationApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from safety_dashboard.admin.access import AdminAccessSettings,AdminAccessVerifier
        from safety_dashboard.api.app import create_app
        from safety_dashboard.application.message_spatial import MessageSpatialService
        self.fx=PreparationTests();self.fx.setUp()
        app=create_app(message_record_service=self.fx.records,message_analysis_service=self.fx.analyzer,
                       message_spatial_service=MessageSpatialService(self.fx.records,self.fx.catalog),
                       admin_access_service=AdminAccessVerifier(AdminAccessSettings(password='test-password')))
        self.client=TestClient(app);self.base='/internal/v1/message-records/'+self.fx.record['id']

    def login(self):
        response=self.client.post('/internal/v1/admin/access',json={'password':'test-password'})
        self.assertEqual(response.status_code,200)
        return {'X-Alert-Admin-Token':response.json()['token']}

    def test_new_prepare_approve_and_hold_routes_require_auth_and_no_store(self):
        for suffix in ('prepare','approve','hold'):
            response=self.client.post(self.base+'/'+suffix,json={})
            self.assertEqual(response.status_code,403)
            self.assertIn('no-store',response.headers['cache-control'])

    def test_one_approval_persists_and_can_be_retrieved_without_intermediate_reference_calls(self):
        headers=self.login();req={'expected_version':self.fx.current()['version']}
        preview=self.client.post(self.base+'/prepare',json=req,headers=headers)
        self.assertEqual(preview.status_code,200);self.assertTrue(preview.json()['ready'])
        before=self.fx.current()
        body={**req,'proposal_hash':preview.json()['proposal_hash'],'confirmed':True}
        approved=self.client.post(self.base+'/approve',json=body,headers=headers)
        self.assertEqual(approved.status_code,200);self.assertEqual(approved.json()['version'],before['version']+1)
        self.assertEqual(self.client.get(self.base,headers=headers).json()['review_state'],'completed')
        self.assertEqual(self.client.post(self.base+'/approve',json=body,headers=headers).json()['version'],before['version']+1)
        self.assertTrue(self.client.get(self.base+'/review',headers=headers).json()['draft_current'])

    def test_store_failure_is_safe_and_does_not_leave_a_confirmed_reference(self):
        headers=self.login();req={'expected_version':self.fx.current()['version']}
        preview=self.client.post(self.base+'/prepare',json=req,headers=headers).json()
        original=self.fx.records.store.commit
        self.fx.records.store.commit=Mock(side_effect=RuntimeError('private-upstream-error'))
        try:
            response=self.client.post(self.base+'/approve',json={**req,'proposal_hash':preview['proposal_hash'],'confirmed':True},headers=headers)
            self.assertEqual(response.status_code,503);self.assertNotIn('private-',response.text)
            self.assertFalse(self.fx.current()['spatial_references'])
        finally:self.fx.records.store.commit=original
