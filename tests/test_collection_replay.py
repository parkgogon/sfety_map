import copy
import datetime as dt
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import requests

import yaml

from scripts.diagnose_collection_runtime import diagnose, handler
from safety_dashboard.application.message_pipeline import MemoryPipelineStore, stamp
from tests.test_message_automation import FakeFeed, message, NOW


class CollectionReplayTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryPipelineStore()
        self.store.values['collection-state'] = {'start_at':stamp(NOW-dt.timedelta(minutes=1)),
            'work':[{'region':None, 'date':NOW.date().isoformat(), 'page':1, 'offset':0}]}

    def test_replay_uses_deep_memory_copy_and_never_exports_source_ids_or_text(self):
        feed=FakeFeed({(None,NOW.date(),1):([message('private-id',text='private source text is sufficiently long')],True,0)})
        before=copy.deepcopy(self.store.values)
        report=diagnose(store=self.store,provider=feed,now=lambda:NOW)
        self.assertEqual(report['status'],'passed')
        self.assertEqual(report['feed_calls'],2)
        self.assertEqual(report['production_documents_written'],0)
        self.assertEqual(self.store.values,before)
        self.assertNotIn('private',json.dumps(report))

    def test_error_before_provider_is_localized_without_exception_message(self):
        self.store.values['collection-state']['work'][0].pop('region')
        feed=FakeFeed()
        report=diagnose(store=self.store,provider=feed,now=lambda:NOW)
        self.assertEqual(report['replay_result']['state'],'error')
        self.assertEqual(report['feed_calls'],0)
        self.assertTrue(any(e['type']=='KeyError' and e['file']=='message_collection.py' for e in report['exceptions']))

    def test_repeated_private_request_does_not_repeat_feed_reads(self):
        run=Mock(return_value={'status':'passed'})
        cls=handler(run);request=cls.__new__(cls)
        request.path='/verify';request.headers={};request.wfile=io.BytesIO()
        request.send_response=Mock();request.send_header=Mock();request.end_headers=Mock()
        request.do_POST();request.do_POST()
        run.assert_called_once()

    def test_connect_timeout_uses_only_one_bounded_comparison(self):
        feed=Mock(configured=True)
        feed.fetch_page.side_effect=requests.ConnectTimeout('private-key')
        compare=Mock(return_value={'status':'passed'})
        report=diagnose(store=self.store,provider=feed,now=lambda:NOW,compare=compare)
        self.assertEqual(report['feed_calls'],2)
        self.assertEqual(report['transport_comparison']['status'],'passed')
        compare.assert_called_once()
        self.assertNotIn('private-key',json.dumps(report))

    def test_candidate_replay_supplies_current_and_history_priorities_without_writes(self):
        feed=Mock(configured=True)
        feed.fetch_page.return_value={'messages':[],'has_more':False,'skipped':0}
        before=copy.deepcopy(self.store.values)
        with patch.dict('os.environ',{'COLLECTION_PROBE_CANDIDATE':'true','COLLECTION_CANDIDATE_REVISION':'a'*40}):
            report=diagnose(store=self.store,provider=feed,now=lambda:NOW)
        self.assertEqual(report['replay_result']['state'],'partial')
        self.assertEqual({c.kwargs['priority'] for c in feed.fetch_page.call_args_list},{'latest','background'})
        self.assertEqual(self.store.values,before)

    def test_workflow_only_binds_feed_key_and_deletes_own_private_service(self):
        config=yaml.safe_load((Path(__file__).resolve().parents[1]/'.github/workflows/check-message-review-deployment.yml').read_text())
        job=config['jobs']['collection-diagnostics']
        self.assertIn("inputs.mode == 'collection-diagnostics'",job['if'])
        deploy=next(s['run'] for s in job['steps'] if s.get('name','').startswith('Run isolated'))
        self.assertIn('--no-allow-unauthenticated',deploy)
        self.assertIn('5f58be1d12a8ac57c0ec365e4eeb86b392fc348c',deploy)
        for forbidden in ('OPENAI','TELEGRAM','ADMIN_ACCESS','KMA_API','dispatch'):
            self.assertNotIn(forbidden,deploy)
        self.assertTrue(any(s.get('if')=='always()' and 'services delete "$CHECK_SERVICE"' in s.get('run','') for s in job['steps']))
