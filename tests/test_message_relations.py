import copy
import datetime as dt
import unittest
import uuid
from unittest.mock import Mock

from fastapi.testclient import TestClient
from pydantic import ValidationError
from safety_dashboard.admin.access import AdminAccessSettings, AdminAccessVerifier
from safety_dashboard.api.app import create_app
from safety_dashboard.adapters.firestore_message_records import FirestoreMessageRecordStore
from safety_dashboard.application.message_records import AnalyzeRecord, RegisterMessage, RecordConflict, SaveRecordNote
from safety_dashboard.application.message_relations import MessageRelationService, LinkMessage, UnlinkMessage, RelationValidationError, compare_segments, region_hint
from safety_dashboard.application.message_review import MessageReviewService, CompleteMessageReview, CopyMessageNotice, ReviewValidationError
from tests.test_message_records import make_service, NOW


def analysis(release=False):
    def part(name, intent):
        return {'intent':intent,'evidence':name+(' 통제 해제' if intent=='release' else ' 통제 유지'),
                'starts_at':None,'ends_at':'2026-11-08T15:00:00+09:00' if intent=='release' else None,
                'locations':[{'text':name,'role':'restricted_area','candidate_ids':[],'evidence':name}]}
    return {'analysis':{'summary':'구간별 통제','questions':[], 'parts':[
        part('가람교','release' if release else 'active_restriction'),part('푸른교','active_restriction')]},'candidates':[]}


class RelationTests(unittest.TestCase):
    def setUp(self):
        self.analyzer=Mock(); self.analyzer.analyze.return_value=analysis()
        self.records=make_service(self.analyzer); self.relations=MessageRelationService(self.records)
        self.review=MessageReviewService(self.records,Mock(return_value=('1'*64,())),self.relations.context)
        self.parent=self.add(0);self.analyzer.analyze.return_value=analysis(True);self.target=self.add(1)

    def add(self, hour, *, regions=None, origin='example', official=None):
        message={'text':f'{hour}시 가람교와 푸른교 구간별 통제 안내입니다.', 'source':'창작 검수 문자',
                 'issued_at':(NOW+dt.timedelta(hours=hour)).isoformat(),'recipient_regions':regions if regions is not None else ['경상북도 구미시']}
        if official:
            r=self.records.register_official(message,official,NOW.isoformat())['record']
        else:
            r=self.records.register_manual(RegisterMessage(**message,input_kind=origin,registration_key=uuid.uuid4()))['record']
        return self.records.analyze(r['id'],AnalyzeRecord(expected_version=r['version']))

    def link(self, parent=None, target=None, **kwargs):
        parent=parent or self.parent;target=target or self.target
        preview=self.relations.preview(parent['id'],target['id'])
        return self.relations.link(parent['id'],LinkMessage(**{'expected_version':self.records.get(parent['id'])['version'],
            'target_id':target['id'],'kind':'release','reason':'동일 사건의 일부 구간 해제 안내 확인','confirmed':True,
            'comparison_token':preview['comparison_token'],**kwargs}))

    def complete(self,parent=None,note='가람교 해제와 푸른교 통제 유지 별도 확인'):
        parent=parent or self.parent;r=self.records.get(parent['id'])
        return self.review.complete(r['id'],CompleteMessageReview(expected_version=r['version'],outcome='no_action',reason='내부 판단 검수',follow_up_note=note))

    def test_partial_release_comparison_keeps_independent_segments_and_originals(self):
        old=copy.deepcopy(self.parent);target=copy.deepcopy(self.target)
        preview=self.relations.preview(old['id'],target['id']);comp=preview['comparison']
        self.assertTrue(comp['has_release']);self.assertTrue(comp['has_active_restriction'])
        self.assertEqual([(r['text'],r['before']['intent'],r['after']['intent']) for r in comp['locations']],
            [('가람교','active_restriction','release'),('푸른교','active_restriction','active_restriction')])
        linked=self.link();self.assertEqual(linked['analysis'],old['analysis']);self.assertEqual(linked['message'],old['message'])
        self.assertEqual(self.records.get(target['id']),target);self.assertEqual(self.analyzer.analyze.call_count,2)
        self.assertFalse(self.relations.detail(old['id'])['needs_reconfirm'])

    def test_link_invalidates_completed_notice_and_requires_followup_note(self):
        completed=self.complete(note='');linked=self.link()
        self.assertEqual(linked['review_state'],'needs_confirmation');self.assertIsNone(linked['notice_draft'])
        with self.assertRaises(ReviewValidationError):self.complete(note='')
        new=self.complete();text=new['notice_draft']['text']
        self.assertIn(self.target['message']['text'],text);self.assertIn('해제: 가람교',text);self.assertIn('통제 유지: 푸른교',text)
        self.assertIn('전체 해제 추정 금지',text)
        self.assertTrue(any(v['record'].get('notice_draft')==completed['notice_draft'] for v in self.records.store.history(self.parent['id'],None,50)))

    def test_target_reanalysis_invalidates_completion_and_copy_without_parent_write(self):
        self.link();completed=self.complete();before=self.records.get(self.parent['id'])
        changed=self.records.analyze(self.target['id'],AnalyzeRecord(expected_version=self.target['version']))
        self.assertTrue(self.relations.detail(self.parent['id'])['needs_reconfirm'])
        self.assertFalse(self.review.detail(self.parent['id'])['draft_current'])
        with self.assertRaises(RecordConflict):self.review.copy_draft(self.parent['id'],CopyMessageNotice(expected_version=completed['version'],draft_revision=1))
        self.assertEqual(self.records.get(self.parent['id']),before)
        self.link(target=changed);self.assertTrue(self.review.detail(self.parent['id'])['stale_reason']=='')
        self.assertTrue(self.review.detail(self.complete()['id'])['draft_current'])

    def test_unlink_preserves_records_and_history_and_does_not_restore_old_completion(self):
        self.complete(note='');linked=self.link();completed=self.complete()
        unlinked=self.relations.unlink(self.parent['id'],UnlinkMessage(expected_version=completed['version'],target_id=self.target['id'],reason='다른 상황으로 확인되어 연결 해제'))
        self.assertEqual(unlinked['related_messages'],{});self.assertEqual(unlinked['relation_epoch'],linked['relation_epoch']+1)
        self.assertIsNone(unlinked['review_completion']);self.assertIsNone(unlinked['notice_draft'])
        self.assertEqual(self.records.get(self.target['id']),self.target)
        self.assertEqual(unlinked['relation_last_change']['reason'],'다른 상황으로 확인되어 연결 해제')
        self.assertTrue(any(self.target['id'] in row['record'].get('related_messages',{}) for row in self.records.store.history(self.parent['id'],None,50)))

    def test_disjoint_city_same_name_needs_explicit_cross_region_evidence(self):
        other=self.add(2,regions=['경상북도 포항시'])
        self.assertEqual(self.relations.preview(self.parent['id'],other['id'])['regions']['status'],'disjoint')
        with self.assertRaises(RelationValidationError):self.link(target=other)
        with self.assertRaises(RelationValidationError):self.link(target=other,cross_region_confirmed=True)
        self.link(target=other,cross_region_confirmed=True,cross_region_reason='구미와 포항에 걸친 광역 상황 별도 확인')
        self.assertIn('포항',self.records.get(self.parent['id'])['related_messages'][other['id']]['cross_region_reason'])

    def test_missing_region_is_unknown_and_requires_manual_confirmation_not_issuer_inference(self):
        unknown=self.add(2,regions=[])
        self.assertEqual(self.relations.preview(self.parent['id'],unknown['id'])['regions']['status'],'unknown')
        with self.assertRaises(RelationValidationError):self.link(target=unknown,confirmed=False)
        self.link(target=unknown)
        a=copy.deepcopy(self.parent);a['message']['recipient_regions']=['경북 구미시']
        self.assertEqual(region_hint(a,self.parent)['status'],'overlap')

    def test_examples_cannot_mix_with_real_or_official_records(self):
        for kind in ['manual','official']:
            target=self.add(2,origin=kind,official='official-1' if kind=='official' else None)
            with self.assertRaises(RelationValidationError):self.link(target=target)

    def test_self_reverse_and_cycles_rejected_by_immutable_order(self):
        for parent,target in [(self.parent,self.parent),(self.target,self.parent)]:
            with self.assertRaises(RelationValidationError):self.relations.preview(parent['id'],target['id'])
        self.link()
        with self.assertRaises(RelationValidationError):self.link(parent=self.target,target=self.parent)

    def test_official_parent_source_update_preserves_links_and_immutable_order_and_requires_reconfirmation(self):
        parent=self.add(0,official='P');target=self.add(1,official='T');linked=self.link(parent,target)
        updated=self.records.register_official({**parent['message'],'text':'정정된 원문으로 발생 지점을 변경하여 안내합니다.',
            'issued_at':(NOW+dt.timedelta(hours=3)).isoformat()},'P',(NOW+dt.timedelta(minutes=1)).isoformat())['record']
        self.assertEqual(updated['related_messages'],linked['related_messages']);self.assertEqual(updated['relation_order'],parent['relation_order'])
        self.assertTrue(self.relations.detail(parent['id'])['needs_reconfirm'])
        self.records.analyze(parent['id'],AnalyzeRecord(expected_version=updated['version']))
        self.link(parent,target)  # Mutable corrected issue time does not reverse the edge or allow a cycle.
        self.assertFalse(self.relations.detail(parent['id'])['needs_reconfirm'])

    def test_preview_token_detects_target_or_parent_changes(self):
        preview=self.relations.preview(self.parent['id'],self.target['id'])
        self.records.analyze(self.target['id'],AnalyzeRecord(expected_version=self.target['version']))
        with self.assertRaises(RecordConflict):self.link(comparison_token=preview['comparison_token'])
        with self.assertRaises(RecordConflict):self.link(expected_version=1)

    def test_nested_followup_changes_invalidate_upstream_even_after_local_reconfirmation(self):
        third=self.add(2);self.link();self.link(self.target,third)
        self.assertTrue(self.relations.detail(self.parent['id'])['needs_reconfirm'])
        self.link();self.complete()
        self.records.analyze(third['id'],AnalyzeRecord(expected_version=third['version']))
        self.assertTrue(self.relations.detail(self.parent['id'])['needs_reconfirm'])
        with self.assertRaises(RecordConflict):self.complete()
        self.link(self.target,third);self.link()
        self.assertFalse(self.relations.detail(self.parent['id'])['needs_reconfirm'])

    def test_same_name_omission_different_suffix_and_duplicate_names_are_not_automatic_releases(self):
        a,b=copy.deepcopy(self.parent),copy.deepcopy(self.target)
        b['analysis']['analysis']['parts']=[analysis(True)['analysis']['parts'][0]]
        self.assertEqual(compare_segments(a,b)['locations'][1]['status'],'earlier_only')
        b['analysis']['analysis']['parts'][0]['locations'][0]['text']='가람교 하부도로'
        comp=compare_segments(a,b)
        self.assertNotIn('same_spelling',[x['status'] for x in comp['locations']])
        b['analysis']['analysis']['parts']=[analysis(True)['analysis']['parts'][0]]*2
        comp=compare_segments(a,b)
        self.assertNotIn('same_spelling',[x['status'] for x in comp['locations']])

    def test_unanalyzed_or_running_target_cannot_be_linked(self):
        for state in ['not_analyzed','running']:
            target=self.records.get(self.target['id']);target['analysis_state']=state
            if state=='not_analyzed':target['analysis']=None
            self.records.store.commit(target,target['version'],'fixture')
            with self.assertRaises(RecordConflict):self.relations.preview(self.parent['id'],target['id'])

    def test_storage_failure_does_not_claim_link_success(self):
        before=self.records.get(self.parent['id']);commit=self.records.store.commit
        self.records.store.commit=Mock(side_effect=RuntimeError('private-storage-token'))
        with self.assertRaises(RuntimeError):self.link()
        self.records.store.commit=commit;self.assertEqual(self.records.get(self.parent['id']),before)

    def test_depth_limit_blocks_excessive_chain_without_partial_write(self):
        rows=[self.parent,self.target]+[self.add(i) for i in range(2,6)]
        for a,b in reversed(list(zip(rows[1:],rows[2:]))):self.link(a,b)
        before=self.records.get(rows[0]['id'])
        with self.assertRaises(RecordConflict):self.link(rows[0],rows[1])
        self.assertEqual(self.records.get(rows[0]['id']),before)

    def test_legacy_no_relation_snapshot_shape_is_unchanged(self):
        other_review=MessageReviewService(self.records,self.review.catalog)
        self.assertEqual(other_review._snapshot(self.parent),self.review._snapshot(self.parent))

    def test_target_note_and_identical_official_observation_do_not_change_source_basis(self):
        parent=self.add(0,official='P');target=self.add(1,official='T');self.link(parent,target)
        completed=self.complete(parent)
        noted=self.records.save_note(target['id'],SaveRecordNote(expected_version=target['version'],review_state='needs_confirmation',note='별도 업무 메모'))
        self.records.register_official(noted['message'],'T',(NOW+dt.timedelta(minutes=1)).isoformat())
        self.assertFalse(self.relations.detail(parent['id'])['needs_reconfirm'])
        self.assertTrue(self.review.detail(parent['id'])['draft_current'])
        self.assertEqual(self.review.copy_draft(parent['id'],CopyMessageNotice(expected_version=completed['version'],draft_revision=1))['text'],completed['notice_draft']['text'])

    def test_child_link_then_unlink_does_not_resurrect_upstream_completed_basis(self):
        self.link();self.complete();third=self.add(2)
        linked=self.link(self.target,third)
        self.relations.unlink(self.target['id'],UnlinkMessage(expected_version=linked['version'],target_id=third['id'],reason='다른 상황 확인'))
        self.assertTrue(self.relations.detail(self.parent['id'])['needs_reconfirm'])
        self.assertFalse(self.review.detail(self.parent['id'])['draft_current'])

    def test_direct_limit_and_record_versions_are_saved_without_modifying_selected_facilities(self):
        parent=self.records.get(self.parent['id']);parent['spatial_references']={'fixture-selection':{'selected':[{'id':'facility-id'}]}}
        self.records.store.commit(parent,parent['version'],'fixture')
        for hour in range(1,11):self.link(target=self.target if hour==1 else self.add(hour))
        before=self.records.get(parent['id'])
        self.assertEqual(before['spatial_references'],parent['spatial_references'])
        self.assertEqual(before['related_messages'][self.target['id']]['target_record_version'],self.target['version'])
        with self.assertRaises(RelationValidationError):self.link(target=self.add(11))
        self.assertEqual(self.records.get(parent['id']),before)

    def test_unordered_firestore_batch_results_do_not_change_completed_basis(self):
        third=self.add(2);fourth=self.add(3);self.link(self.target,third);self.link(self.target,fourth);self.link()
        self.complete();old=self.records.store.get_many
        self.records.store.get_many=lambda ids:dict(reversed(list(old(ids).items())))
        self.assertTrue(self.review.detail(self.parent['id'])['draft_current'])


class RelationRouteTests(unittest.TestCase):
    add=RelationTests.add
    def setUp(self):
        RelationTests.setUp(self)
        self.client=TestClient(create_app(admin_access_service=AdminAccessVerifier(AdminAccessSettings(password='test-pass')),
            message_record_service=self.records))
        self.base='/internal/v1/message-records/'+self.parent['id']

    def test_all_relationship_routes_are_protected_without_storage_access(self):
        self.records.store_factory=Mock(side_effect=AssertionError('unauthorized'));self.records._store=None
        body={'expected_version':1,'target_id':self.target['id'],'reason':'검수'}
        for method,path,data in [('GET','/related',None),('GET','/related/candidates',None),
            ('GET','/related/preview?target_id='+self.target['id'],None),('POST','/related',{**body,'kind':'release','confirmed':True,'comparison_token':'a'*64}),
            ('POST','/related/unlink',body)]:
            response=self.client.request(method,self.base+path,json=data)
            self.assertEqual(response.status_code,403);self.assertEqual(response.headers['cache-control'],'private, no-store')
        self.records.store_factory.assert_not_called()

    def test_compare_link_complete_target_change_copy_conflict_and_unlink(self):
        self.assertEqual(self.client.post('/internal/v1/admin/access',json={'password':'test-pass'}).status_code,200)
        preview=self.client.get(self.base+'/related/preview',params={'target_id':self.target['id']}).json()
        body={'expected_version':self.parent['version'],'target_id':self.target['id'],'reason':'동일 사건 확인',
              'kind':'release','confirmed':True,'comparison_token':preview['comparison_token']}
        linked=self.client.post(self.base+'/related',json=body);self.assertEqual(linked.status_code,200,linked.text)
        self.assertEqual(self.client.post(self.base+'/related',json=body).status_code,409)
        completed=self.client.post(self.base+'/complete',json={'expected_version':linked.json()['version'],'outcome':'no_action','reason':'구간별 검토','follow_up_note':'푸른교 유지 별도 확인'})
        self.assertEqual(completed.status_code,200,completed.text)
        self.records.analyze(self.target['id'],AnalyzeRecord(expected_version=self.target['version']))
        self.assertFalse(self.client.get(self.base+'/review').json()['draft_current'])
        self.assertEqual(self.client.post(self.base+'/notice-copy',json={'expected_version':completed.json()['version'],'draft_revision':1}).status_code,409)
        unlinked=self.client.post(self.base+'/related/unlink',json={'expected_version':completed.json()['version'],'target_id':self.target['id'],'reason':'잘못 연결한 관계 해제'})
        self.assertEqual(unlinked.status_code,200);self.assertIsNone(unlinked.json()['notice_draft'])
        self.assertEqual(self.client.get(self.base+'/related/preview',params={'target_id':'../bad'}).status_code,404)

    def test_provider_errors_are_generic_and_no_partial_relation_is_saved(self):
        self.client.post('/internal/v1/admin/access',json={'password':'test-pass'})
        self.records.store.get_many=Mock(side_effect=RuntimeError('private-storage-token'))
        linked=self.records.get(self.parent['id']);linked['related_messages']={self.target['id']:{}}
        self.records.store.commit(linked,linked['version'],'fixture')
        response=self.client.get(self.base+'/related')
        self.assertEqual(response.status_code,503);self.assertNotIn('private-storage-token',response.text)


class RelationStorageTests(unittest.TestCase):
    def test_firestore_batch_get_uses_bounded_timeout_and_omits_missing_documents(self):
        client=Mock();snap=Mock(id='id-1',exists=True);snap.to_dict.return_value={'id':'id-1'}
        missing=Mock(id='id-2',exists=False);client.get_all.return_value=[missing,snap]
        store=FirestoreMessageRecordStore(client=client)
        self.assertEqual(store.get_many(['id-1','id-2']),{'id-1':{'id':'id-1'}})
        client.get_all.assert_called_once_with([store.records.document.return_value]*2,timeout=5)
