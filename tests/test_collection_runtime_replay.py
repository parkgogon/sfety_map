import copy
import datetime as dt
import json
import os
import unittest
from unittest.mock import patch

from scripts.diagnose_collection_runtime import diagnose
from safety_dashboard.application.message_pipeline import MemoryPipelineStore, stamp


class RuntimeReplayTests(unittest.TestCase):
    def test_current_strategy_replay_never_writes_back_to_production_state(self):
        now=dt.datetime.fromisoformat('2026-11-10T09:00:00+09:00')
        store=MemoryPipelineStore()
        store.values['collection-state']={'start_at':stamp(now-dt.timedelta(minutes=1)),'work':[],
            'last_error':'collection_failed','last_error_stage':'fetch_page','private':'private-original'}
        before=copy.deepcopy(store.values)
        class Feed:
            configured=True
            calls=0
            def fetch_page(self,*args,**kwargs):
                self.calls+=1
                return {'messages':[],'skipped':0,'has_more':False}
        feed=Feed()
        with patch.dict(os.environ,{'COLLECTION_PROBE_RECENT':'true'}):
            result=diagnose(store=store,provider=feed,now=lambda:now)
        self.assertEqual(store.values,before)
        self.assertEqual(feed.calls,2)
        self.assertEqual(result['candidate_strategy'],'recent_window_v2')
        self.assertEqual(result['production_documents_written'],0)
        self.assertEqual(result['model_calls'],0)
        self.assertNotIn('private-original',json.dumps(result))

    def test_current_strategy_exception_is_classified_without_exporting_error_or_key(self):
        now=dt.datetime.fromisoformat('2026-11-10T09:00:00+09:00')
        store=MemoryPipelineStore();store.values['collection-state']={'start_at':stamp(now),'work':[]}
        class Feed:
            configured=True
            def fetch_page(self,*args,**kwargs):raise TimeoutError('private-key-url')
        with patch.dict(os.environ,{'COLLECTION_PROBE_RECENT':'true'}):
            result=diagnose(store=store,provider=Feed(),now=lambda:now)
        self.assertEqual(result['replay_result']['state'],'error')
        self.assertIn('TimeoutError',{e['type'] for e in result['exceptions']})
        self.assertNotIn('private-key',json.dumps(result))
