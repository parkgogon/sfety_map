import copy
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient
from safety_dashboard.admin.access import AdminAccessSettings, AdminAccessVerifier
from safety_dashboard.api.app import create_app
from safety_dashboard.adapters.facility_csv import CsvFacilityRepository
from safety_dashboard.application.message_records import AnalyzeRecord, RecordConflict, SaveRecordNote
from safety_dashboard.application.message_spatial import MessageSpatialService, SaveMessageReference, SaveMessageSelection
from safety_dashboard.application.message_analysis import AnalysisUnavailable
from safety_dashboard.application.nearby_report import EARTH_RADIUS_METERS
from safety_dashboard.domain.models import Facility, GeoPoint
from tests.test_message_records import make_service, registration, NOW

D1, D2 = '1' * 64, '2' * 64


def facility(identifier, distance=0, name=None):
    return Facility(id=identifier, name=name or f'시설 {identifier}', facility_type='측정소',
        address=f'대구 달서구 {identifier}', location=GeoPoint(35.85 + distance / EARTH_RADIUS_METERS * 180 / math.pi, 128.5),
        manager='private-manager', department='private-department', metadata={'phone': 'private-phone'})


def result():
    def loc(text, role, ids): return {'text': text, 'role': role, 'evidence': text, 'candidate_ids': ids}
    return {'analysis': {'summary': '검수용', 'questions': [], 'parts': [
        {'intent': 'event', 'locations': [loc('성서산업단지', 'incident_site', ['P1']), loc('성서초등학교', 'evacuation_destination', ['P2'])]},
        {'intent': 'active_restriction', 'locations': [loc('중앙동 사거리', 'restricted_area', [])]},
        {'intent': 'release', 'locations': [loc('가람교', 'restricted_area', [])]},
        {'intent': 'prevention', 'locations': [loc('와룡산', 'reference', [])]},
    ]}, 'candidates': [
        {'id': 'P1', 'name': '성서산업단지', 'role': 'incident_site', 'address': '대구 달서구', 'latitude': 35.85, 'longitude': 128.5, 'scope_matches_source': True},
        {'id': 'P2', 'name': '성서초등학교', 'role': 'evacuation_destination', 'address': '대구 달서구', 'latitude': 35.86, 'longitude': 128.51},
    ]}


class SpatialTests(unittest.TestCase):
    def setUp(self):
        self.analyzer = Mock(); self.analyzer.analyze.return_value = result()
        self.records = make_service(self.analyzer)
        self.record = self.records.register_manual(registration())['record']
        self.record = self.records.analyze(self.record['id'], AnalyzeRecord(expected_version=1))
        self.catalog = Mock(return_value=(D1, tuple([facility(str(i), i * 10) for i in range(25)] + [facility('far', 8000)])))
        self.svc = MessageSpatialService(self.records, self.catalog)

    def current(self): return self.records.get(self.record['id'])

    def reference(self, key='0:0', point=None, radius=3, **kwargs):
        return self.svc.save_reference(self.record['id'], SaveMessageReference(
            expected_version=self.current()['version'], location_key=key,
            point=point or {'mode': 'candidate', 'candidate_id': 'P1'}, radius_km=radius,
            confirmation_note='산업단지 대표점을 참고 조회 위치로 사용', confirmed=True, **kwargs))

    def selection(self, ids, key='0:0', reasons=None):
        rec = self.current(); ref = rec['spatial_references'][key]
        return SaveMessageSelection(expected_version=rec['version'], location_key=key,
            reference_revision=ref['revision'], catalog_digest=ref['catalog_digest'], note='업무상 확인 필요',
            facilities=[{'facility_id': identifier, 'reason': (reasons or {}).get(identifier, '')} for identifier in ids])

    def test_reference_and_complete_pagination_use_csv_without_another_ai_call_or_private_metadata(self):
        rec = self.reference()
        self.assertEqual(rec['spatial_references']['0:0']['selected'], [])
        first = self.svc.facilities_page(rec['id'], '0:0', rec['version'])
        second = self.svc.facilities_page(rec['id'], '0:0', rec['version'], offset=first['next_offset'])
        self.assertEqual(first['total_count'], 25); self.assertEqual(len(first['facilities']), 20)
        self.assertEqual(len(second['facilities']), 5); self.assertIsNone(second['next_offset'])
        self.assertEqual(len(first['map_facilities']), 25)
        self.assertEqual(len({f['id'] for f in first['facilities'] + second['facilities']}), 25)
        self.assertNotIn('private-', str(first)); self.assertNotIn('private-', str(second))
        self.assertEqual(self.analyzer.analyze.call_count, 1)

    def test_destination_release_and_reference_roles_cannot_become_incident_query_points(self):
        for key in ('0:1', '3:0', '4:0', '99:0'):
            with self.subTest(key=key), self.assertRaises(ValueError): self.reference(key)
        with self.assertRaises(ValueError): self.reference(point={'mode': 'candidate', 'candidate_id': 'P2'})
        self.assertNotIn('0:1', self.current()['spatial_references'])
        detail = self.svc.detail(self.record['id'])
        self.assertEqual([r['eligible'] for r in detail['locations']], [True, False, True, False, False])

    def test_manual_coordinate_has_distinct_provenance_and_does_not_rewrite_ai_or_original(self):
        original = copy.deepcopy(self.current())
        rec = self.reference('1:0', {'mode': 'manual', 'latitude': 35.85, 'longitude': 128.5, 'manual_source': 'map'})
        point = rec['spatial_references']['1:0']['point']
        self.assertEqual(point['source'], 'map'); self.assertIsNone(point['candidate_id'])
        self.assertEqual(rec['analysis'], original['analysis']); self.assertEqual(rec['message'], original['message'])
        with self.assertRaises(ValueError): self.reference(point={'mode': 'candidate', 'candidate_id': 'P1', 'latitude': 35})
        with self.assertRaises(ValueError): self.reference('1:0', {'mode': 'manual', 'latitude': 35.85})

    def test_confirmation_and_finite_coordinate_are_required(self):
        payload = dict(expected_version=self.current()['version'], location_key='0:0', point={'mode': 'candidate', 'candidate_id': 'P1'}, radius_km=3, confirmation_note='확인 근거')
        for extras in ({'confirmed': False}, {'confirmed': True, 'confirmation_note': ''},
                       {'confirmed': True, 'point': {'mode': 'manual', 'latitude': float('nan'), 'longitude': 128}}):
            with self.assertRaises(ValueError): SaveMessageReference(**{**payload, **extras})

    def test_selection_reloads_with_computed_distances_and_separate_outside_reason(self):
        self.reference()
        with self.assertRaises(ValueError): self.svc.save_selection(self.record['id'], self.selection(['far']))
        req = self.selection(['0', 'far'], reasons={'far': '거리 밖이지만 같은 접근도로 사용'})
        rec = self.svc.save_selection(self.record['id'], req)
        ref = self.svc.detail(rec['id'])['locations'][0]['reference']
        self.assertEqual([f['id'] for f in ref['selected']], ['0', 'far'])
        self.assertEqual(ref['selected'][1]['distance_m'], 8000)
        self.assertEqual(ref['selected'][1]['reason'], '거리 밖이지만 같은 접근도로 사용')
        self.assertNotIn('private-', str(ref)); self.assertEqual(self.analyzer.analyze.call_count, 1)

    def test_invalid_duplicate_or_invented_facility_fields_cannot_be_saved(self):
        self.reference()
        for ids in (['invented'], ['0', '0']):
            with self.assertRaises(ValueError): self.svc.save_selection(self.record['id'], self.selection(ids))
        req = self.selection(['0']).model_copy(update={'note': ''})
        with self.assertRaises(ValueError): self.svc.save_selection(self.record['id'], req)
        with self.assertRaises(ValueError): SaveMessageSelection.model_validate({**self.selection(['0']).model_dump(), 'facilities': [{'facility_id': '0', 'distance_m': 0}]})

    def test_boundary_membership_uses_unrounded_distance(self):
        self.catalog.return_value = D1, (facility('inside', 2999.9), facility('outside', 3000.1))
        rec = self.reference()
        page = self.svc.facilities_page(rec['id'], '0:0', rec['version'], scope='all')
        self.assertEqual([f['distance_m'] for f in page['facilities']], [3000, 3000])
        self.assertEqual([f['within_radius'] for f in page['facilities']], [True, False])
        with self.assertRaises(ValueError): self.svc.save_selection(rec['id'], self.selection(['outside']))

    def test_radius_or_point_change_resets_selection_and_keeps_history(self):
        self.reference(); selected = self.svc.save_selection(self.record['id'], self.selection(['0']))
        old_ref = selected['spatial_references']['0:0']
        changed = self.reference(radius=1)
        ref = changed['spatial_references']['0:0']
        self.assertEqual(ref['selected'], []); self.assertTrue(ref['selection_needs_review'])
        old_request = self.selection(['0']).model_copy(update={'reference_revision': old_ref['revision']})
        with self.assertRaises(RecordConflict): self.svc.save_selection(changed['id'], old_request)
        self.assertTrue(any(v['record'].get('spatial_references', {}).get('0:0', {}).get('selected') for v in self.records.store.history(changed['id'], None, 50)))
        self.assertEqual(self.analyzer.analyze.call_count, 1)

    def test_reconfirming_identical_criteria_preserves_saved_selection(self):
        self.reference(); before = self.svc.save_selection(self.record['id'], self.selection(['0']))
        after = self.reference()
        self.assertEqual(after['spatial_references']['0:0']['revision'], before['spatial_references']['0:0']['revision'])
        self.assertEqual(after['spatial_references']['0:0']['selected'], before['spatial_references']['0:0']['selected'])

    def test_two_incident_locations_remain_independent(self):
        self.reference(); self.svc.save_selection(self.record['id'], self.selection(['0']))
        self.reference('1:0', {'mode': 'manual', 'latitude': 35.85, 'longitude': 128.5, 'manual_source': 'coordinate'})
        rec = self.svc.save_selection(self.record['id'], self.selection(['1'], key='1:0'))
        self.assertEqual(rec['spatial_references']['0:0']['selected'][0]['id'], '0')
        self.assertEqual(rec['spatial_references']['1:0']['selected'][0]['id'], '1')

    def test_catalog_change_blocks_stale_selection_until_reference_is_refreshed(self):
        self.reference(); self.svc.save_selection(self.record['id'], self.selection(['0']))
        old_request = self.selection(['0'])
        self.catalog.return_value = D2, (facility('0', 5000, '변경된 시설'),)
        self.assertFalse(self.svc.detail(self.record['id'])['locations'][0]['catalog_current'])
        with self.assertRaises(RecordConflict): self.svc.save_selection(self.record['id'], old_request)
        with self.assertRaises(RecordConflict): self.svc.facilities_page(self.record['id'], '0:0', self.current()['version'], catalog_digest=D1)
        rec = self.reference()
        self.assertEqual(rec['spatial_references']['0:0']['selected'], [])
        self.assertEqual(rec['spatial_references']['0:0']['nearby_count'], 0)

    def test_search_finds_outside_facilities_and_paging_is_bounded_by_routes(self):
        rec = self.reference()
        page = self.svc.facilities_page(rec['id'], '0:0', rec['version'], scope='all', query='far')
        self.assertEqual(page['total_count'], 1); self.assertFalse(page['facilities'][0]['within_radius'])

    def test_successful_reanalysis_invalidates_references_failure_preserves_them(self):
        rec = self.reference(); self.svc.save_selection(rec['id'], self.selection(['0']))
        self.analyzer.analyze.side_effect = AnalysisUnavailable('safe failure')
        with self.assertRaises(AnalysisUnavailable): self.records.analyze(rec['id'], AnalyzeRecord(expected_version=self.current()['version']))
        self.assertTrue(self.current()['spatial_references'])
        self.analyzer.analyze.side_effect = None
        rec = self.records.analyze(rec['id'], AnalyzeRecord(expected_version=self.current()['version']))
        self.assertEqual(rec['spatial_references'], {}); self.assertEqual(rec['spatial_reset_reason'], 'analysis_changed')
        self.assertIsNone(self.svc.detail(rec['id'])['locations'][0]['reference'])

    def test_official_source_change_clears_current_references_and_preserves_old_history(self):
        original = self.current()["message"]
        self.record = self.records.register_official(original, "official-test-1", NOW.isoformat())["record"]
        self.record = self.records.analyze(self.record["id"], AnalyzeRecord(expected_version=1))
        self.reference()
        updated = self.records.register_official({**original, "text": "공식 문자가 정정되었습니다. 사고 위치는 다른 곳입니다."}, "official-test-1", NOW.isoformat())["record"]
        self.assertEqual(updated["spatial_references"], {})
        self.assertEqual(updated["spatial_reset_reason"], "source_changed")
        self.assertTrue(any(v["record"].get("spatial_references") for v in self.records.store.history(updated["id"], None, 50)))

    def test_stale_version_running_analysis_and_missing_source_analysis_are_blocked(self):
        stale = self.current()['version']; self.reference()
        with self.assertRaises(RecordConflict): self.svc.facilities_page(self.record['id'], '0:0', stale)
        rec = self.current(); rec['analysis_state'] = 'running'; self.records.store.commit(rec, rec['version'], 'test-running')
        with self.assertRaises(RecordConflict): self.svc.detail(rec['id'])
        rec = self.current(); rec['analysis_state'] = 'completed'; rec['analysis_source_revision'] = 999
        self.records.store.commit(rec, rec['version'], 'test-stale-source')
        with self.assertRaises(RecordConflict): self.svc.detail(rec['id'])


class SpatialRouteTests(unittest.TestCase):
    current = SpatialTests.current

    def setUp(self):
        SpatialTests.setUp(self)
        self.client = TestClient(create_app(admin_access_service=AdminAccessVerifier(AdminAccessSettings(password='test-pass')),
            message_record_service=self.records, message_spatial_service=self.svc))
        self.base = '/internal/v1/message-records/' + self.record['id']

    def test_routes_authenticate_before_calculation_and_enforce_page_limits(self):
        for method, path, body in (('GET', '/spatial', None), ('GET', '/facilities?location_key=0:0&expected_version=1', None),
                ('POST', '/reference', {}), ('POST', '/selection', {})):
            response = self.client.request(method, self.base + path, json=body)
            self.assertEqual(response.status_code, 403)
        self.catalog.assert_not_called()
        self.client.post('/internal/v1/admin/access', json={'password': 'test-pass'})
        self.assertEqual(self.client.get(self.base + '/spatial').status_code, 200)
        response = self.client.post(self.base + '/reference', json={
            'expected_version': self.current()['version'], 'location_key': '0:0', 'point': {'mode': 'candidate', 'candidate_id': 'P1'},
            'confirmed': True, 'confirmation_note': '검수용 기준점 확인', 'radius_km': 3})
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.get(self.base + f'/facilities?location_key=0:0&expected_version={response.json()["version"]}&limit=51')
        self.assertEqual(response.status_code, 422)


class CatalogSnapshotTests(unittest.TestCase):
    def test_snapshot_matches_regular_catalog_and_hashes_exact_parsed_bytes(self):
        import hashlib
        source = Path(__file__).resolve().parents[1] / 'facilities_info.csv'
        repo = CsvFacilityRepository(source)
        digest, facilities = repo.snapshot()
        self.assertEqual(digest, hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(facilities, repo.list_monitored())
