import json
import unittest

from pydantic import ValidationError

from safety_dashboard.application.message_analysis import AnalysisDraft, NotificationSubmission, compatible_place, SearchPlaces
from tests.test_message_analysis import FakeClient, FakePlaces, PLACE, MessageAnalysisService, FACILITIES, call, draft, part, location, request, search_args, service
from tests.test_message_notification import assessment


class MessageAgentRecoveryTests(unittest.TestCase):
    def test_explicit_release_clock_is_preserved_even_when_city_is_unknown(self):
        req=request('partial_release')
        released=part('가람교 하부도로 통제는 15시 해제되었습니다.','release',time_text='')
        active=part('푸른교 하부도로는 침수로 계속 통제 중이니 진입하지 마세요.','active_restriction')
        a=assessment(req.text,need='uncertain',relevance='unknown')
        body=draft([released,active],['푸른교의 시·군은 어디인가요?'])
        fixed={**body,'parts':[{**released,'time_text':'15시','ends_at':'2026-11-07T15:00:00+09:00'},active]}
        agent=service([call('submit_analysis',{**body,'notification_assessment':a}),call('submit_analysis',{**fixed,'notification_assessment':a})])
        result=agent.analyze(req)
        self.assertIn('ends_at',agent.client.inputs[1][-1]['output'])
        self.assertEqual(result['analysis']['parts'][0]['ends_at'],'2026-11-07T15:00:00+09:00')

    def test_ambiguous_release_date_is_not_forced_to_the_issue_date(self):
        text='대구의 도로 통제는 지난달 15시 해제되었습니다. 당시 상황을 참고하세요.'
        body={**draft([part(text,'release',time_text='15시')],['정확한 해제 날짜가 언제인가요?']),
              'notification_assessment':assessment(text,need='uncertain',relevance='unknown')}
        result=service([call('submit_analysis',body)]).analyze(request(text=text))
        self.assertIsNone(result['analysis']['parts'][0]['ends_at'])

    def test_issuer_district_is_not_used_to_narrow_a_body_city(self):
        req=request('destination')
        wrong=search_args('대구 달서구','incident_site','대구 달서구',search_name='와룡산',place_kind='mountain')
        wrong['evidence']=req.text
        correct={**wrong,'location_text':'대구 와룡산','region_hint':'대구'}
        places=FakePlaces([{**PLACE,'name':'와룡산','address':'대구 서구','category_name':'여행 > 산'}])
        body={**draft([part(req.text,locations=[location('대구 와룡산',candidate_ids=['P1']),location('성서초등학교 운동장','evacuation_destination')])]),
              'notification_assessment':assessment(req.text,refs=['P1'])}
        agent=service([call('search_places',wrong),call('search_places',correct),call('find_nearby_facilities',{'candidate_id':'P1'}),call('submit_analysis',body)],places=places)
        result=agent.analyze(req)
        self.assertIn('location_text',agent.client.inputs[1][-1]['output'])
        self.assertIn('region_hint',agent.client.inputs[1][-1]['output'])
        self.assertEqual(places.queries,['대구 와룡산'])
        self.assertTrue(result['candidates'][0]['scope_matches_source'])

    def test_a_district_explicit_in_the_body_still_blocks_an_outside_candidate(self):
        text='[대구시] 대구 달서구 가람교 도로를 통제합니다. 다른 도로로 우회하세요.'
        args=search_args('가람교','restricted_area','대구 달서구',place_kind='bridge');args['evidence']=text
        places=FakePlaces([{**PLACE,'name':'가람교','address':'대구 서구','category_name':'교통,수송 > 도로시설 > 교량,다리'}])
        body={**draft([part(text,'active_restriction',[location('가람교','restricted_area',['P1'])])],['통제 지점을 확인해야 합니다.']),
              'notification_assessment':assessment(text,need='uncertain',relevance='unknown')}
        agent=service([call('search_places',args),call('find_nearby_facilities',{'candidate_id':'P1'}),call('submit_analysis',body)],places=places)
        result=agent.analyze(request(text=text))
        self.assertFalse(result['candidates'][0]['scope_matches_source'])
        self.assertEqual(result['nearby'],[])
        self.assertEqual(result['trace'][1]['status'],'needs_confirmation')
    def test_unknown_region_notify_is_corrected_without_guessing_a_city(self):
        req=request('ambiguous',recipient_regions=['대구광역시','부산광역시'])
        body=draft([part(req.text,'active_restriction',[location('중앙동 사거리 인근','restricted_area')])],['어느 시·군의 중앙동인가요?'])
        agent=service([call('submit_analysis',{**body,'notification_assessment':assessment(req.text,relevance='area_operations')}),
                       call('submit_analysis',{**body,'notification_assessment':assessment(req.text,need='uncertain',relevance='unknown')})])
        result=agent.analyze(req)
        self.assertEqual(result['analysis']['notification_assessment']['need'],'uncertain')
        self.assertEqual(agent.places.queries,[])
        self.assertIn('need=uncertain',agent.client.inputs[1][-1]['output'])
        self.assertEqual([s['status'] for s in result['trace']],['invalid','ok'])

    def test_destination_basis_is_rejected_then_corrected_within_six_responses(self):
        text='대구 성서산업단지에서 화재가 발생했습니다. 성서초등학교 운동장으로 대피하세요.'
        places=FakePlaces([PLACE,{**PLACE,'name':'성서초등학교','category_name':'교육 > 학교','category_group_code':'SC4'}])
        body=draft([part(text,locations=[location(candidate_ids=['P1']),location('성서초등학교','evacuation_destination',['P2'])])])
        agent=service([call('search_places',search_args()),call('find_nearby_facilities',{'candidate_id':'P1'}),
            call('search_places',search_args('성서초등학교','evacuation_destination')),
            call('submit_analysis',{**body,'notification_assessment':assessment(text,refs=['P1','P2'])}),
            call('submit_analysis',{**body,'notification_assessment':assessment(text,refs=['P1'])})],places=places)
        result=agent.analyze(request(text=text))
        self.assertEqual(result['model_calls'],5)
        self.assertEqual(result['analysis']['notification_assessment']['basis_refs'],['P1'])
        self.assertEqual([r['candidate_id'] for r in result['nearby']],['P1'])
        self.assertIn('대피 목적지',agent.client.inputs[4][-1]['output'])

    def test_released_bridge_cannot_support_an_unlocated_active_restriction(self):
        req=request('partial_release')
        places=FakePlaces([{**PLACE,'name':'가람교','address':'서울 성동구','category_name':'교통,수송 > 도로시설 > 교량,다리'}])
        released=part('가람교 하부도로 통제는 15시 해제되었습니다.','release',[location('가람교 하부도로','restricted_area',['P1'])],
                      time_text='15시',ends_at='2026-11-07T15:00:00+09:00')
        active=part('푸른교 하부도로는 침수로 계속 통제 중이니 진입하지 마세요.','active_restriction',[location('푸른교 하부도로','restricted_area')])
        body=draft([released,active],['푸른교가 위치한 시·군을 확인해야 합니다.'])
        agent=service([call('search_places',search_args('가람교 하부도로','restricted_area',None,search_name='가람교',place_kind='bridge')),
            call('submit_analysis',{**body,'notification_assessment':assessment(req.text,relevance='area_operations',refs=['P1'])}),
            call('submit_analysis',{**body,'notification_assessment':assessment(req.text,need='uncertain',relevance='unknown')})],places=places)
        result=agent.analyze(req)
        self.assertEqual(result['analysis']['notification_assessment']['need'],'uncertain')
        self.assertEqual([p['intent'] for p in result['analysis']['parts']],['release','active_restriction'])
        self.assertEqual(result['nearby'],[])

    def test_repeated_failed_parking_search_is_reused_then_finishes_with_scheduled_times(self):
        req=request('scheduled')
        args=search_args('영천 금호강 둔치 주차장 진입로','restricted_area','영천',search_name='금호강 둔치 주차장',place_kind='parking')
        args['evidence']=req.text
        body=draft([part(req.text,'scheduled_restriction',[location('금호강 둔치 주차장 진입로','restricted_area')],
            time_text='내일 09시부터 12시까지',starts_at='2026-11-08T09:00:00+09:00',ends_at='2026-11-08T12:00:00+09:00')],['정확한 주차장 위치가 어디인가요?'])
        quoted={**args,'evidence':'"'+args['evidence']+'"'}
        agent=service([call('search_places',quoted),call('search_places',args),call('search_places',args),
            call('submit_analysis',{**body,'notification_assessment':assessment(req.text,need='uncertain',urgency='scheduled',relevance='unknown')})],places=FakePlaces([]))
        result=agent.analyze(req)
        self.assertEqual(len(agent.places.queries),1)
        self.assertIn('따옴표',agent.client.inputs[1][-1]['output'])
        self.assertIn('재사용',result['trace'][2]['detail'])
        self.assertEqual(result['analysis']['parts'][0]['starts_at'],'2026-11-08T09:00:00+09:00')
        self.assertEqual(result['analysis']['notification_assessment']['need'],'uncertain')

    def test_issue_timestamp_is_not_repaired_by_inventing_a_time_quote(self):
        req=request('ambiguous')
        body=draft([part(req.text,'active_restriction',[location('중앙동 사거리','restricted_area')])],['어느 시·군인가요?'])
        a=assessment(req.text,need='uncertain',relevance='unknown')
        first={**body,'parts':[{**body['parts'][0],'starts_at':req.issued_at.isoformat()}],'notification_assessment':a}
        second={**first,'parts':[{**first['parts'][0],'time_text':req.issued_at.isoformat()}]}
        agent=service([call('submit_analysis',first),call('submit_analysis',second),call('submit_analysis',{**body,'notification_assessment':a})])
        result=agent.analyze(req)
        self.assertIn('발행 시각을',agent.client.inputs[1][-1]['output'])
        self.assertIn('ISO 날짜',agent.client.inputs[2][-1]['output'])
        self.assertIsNone(result['analysis']['parts'][0]['starts_at'])

    def test_last_two_responses_remain_available_for_submission_and_correction(self):
        req=request('prevention')
        good={**draft([part(req.text,'prevention')]),'notification_assessment':assessment(req.text,need='record_only',relevance='general',urgency='reference')}
        bad={**good,'parts':[{**good['parts'][0],'evidence':'"'+req.text+'"'}]}
        class RecordingClient(FakeClient):
            def respond(self,items,tools,instructions,timeout):
                self.allowed.append([t['name'] for t in tools])
                return super().respond(items,tools,instructions,timeout)
        client=RecordingClient([call('find_nearby_facilities',{'candidate_id':None})]*4+[call('submit_analysis',bad),call('submit_analysis',good)])
        client.allowed=[]
        result=MessageAnalysisService(client,FakePlaces(),lambda:FACILITIES).analyze(req)
        self.assertEqual(result['model_calls'],6)
        self.assertEqual(client.allowed[-2:],[['submit_analysis'],['submit_analysis']])
        self.assertEqual(result['analysis']['notification_assessment']['need'],'record_only')

    def test_invalid_fields_receive_paths_without_the_rejected_values(self):
        req=request('prevention')
        agent=service([call('find_nearby_facilities',{'candidate_id':None}),
            call('submit_analysis',{**draft([part(req.text,'prevention')]),'notification_assessment':assessment(req.text,need='record_only',relevance='general',urgency='reference')})])
        agent.analyze(req)
        feedback=json.loads(agent.client.inputs[1][-1]['output'])
        self.assertEqual(feedback['fields'][0]['path'],'candidate_id')
        self.assertNotIn('input',feedback['fields'][0])
        self.assertEqual(feedback['remaining_model_responses'],5)

    def test_new_tool_contract_requires_assessment_but_old_saved_analysis_still_loads(self):
        body=draft([part(request('prevention').text,'prevention')])
        self.assertIsNone(AnalysisDraft.model_validate(body).notification_assessment)
        with self.assertRaises(ValidationError):NotificationSubmission.model_validate({**body,'notification_assessment':None})

    def test_real_kakao_combined_bridge_category_keeps_a_matching_bridge(self):
        search=SearchPlaces.model_validate(search_args('가람교','restricted_area',None,place_kind='bridge'))
        self.assertTrue(compatible_place(search,{'name':'가람교','address':'서울 성동구','category_name':'교통,수송 > 도로시설 > 교량,다리'}))
