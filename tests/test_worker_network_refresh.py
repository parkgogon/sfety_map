import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from scripts import refresh_worker_network


class WorkerNetworkRefreshTests(unittest.TestCase):
    def service(self):
        return {'spec':{'template':{'spec':{'serviceAccountName':'runtime','containers':[{'image':'registry/worker:'+'a'*40,'env':[{'name':'APP_REVISION','value':'a'*40},{'name':'SECRET','valueFrom':{'secretKeyRef':{'name':'private-ref'}}}],'resources':{'limits':{'cpu':'1','memory':'512Mi'}}}]}}},
            'status':{'latestReadyRevisionName':'safety-alert-worker-old','traffic':[{'revisionName':'safety-alert-worker-old','percent':100}]}}

    def test_changed_worker_aborts_before_mutation(self):
        before=self.service();before['status']['latestReadyRevisionName']='someone-else'
        with patch.dict(os.environ,{'EXPECTED_WORKER_REVISION':'safety-alert-worker-old','EXPECTED_APP_REVISION':'a'*40}),patch('scripts.refresh_worker_network.describe',return_value=before),patch('scripts.refresh_worker_network.subprocess.run') as run:
            with self.assertRaises(ValueError):refresh_worker_network.main()
            run.assert_not_called()

    def test_refresh_changes_only_revision_and_preserves_all_runtime_settings(self):
        before=self.service();after=copy.deepcopy(before)
        after['status']={'latestReadyRevisionName':'safety-alert-worker-new','traffic':[{'revisionName':'safety-alert-worker-new','percent':100}]}
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'EXPECTED_WORKER_REVISION':'safety-alert-worker-old','EXPECTED_APP_REVISION':'a'*40}),patch('scripts.refresh_worker_network.describe',side_effect=[before,after]),patch('scripts.refresh_worker_network.subprocess.run') as run,contextlib.redirect_stdout(io.StringIO()):
            old=os.getcwd()
            try:
                os.chdir(directory);refresh_worker_network.main()
                report=(Path('release-check')/'worker-refresh.json').read_text()
                self.assertTrue(json.loads(report)['same_runtime_spec']);self.assertNotIn('private-ref',report)
                args=run.call_args.args[0]
                self.assertEqual(args[:5],['gcloud','run','services','update','safety-alert-worker'])
                self.assertFalse(any(x.startswith(('--set-env','--set-secret','--image','--memory','--cpu')) for x in args))
            finally:os.chdir(old)
