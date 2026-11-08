import base64
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from safety_dashboard.operations.verify_message_release import allowed_request,emit,verify
from scripts import capture_release_baseline,collect_message_release_check,invoke_message_release_check


class ReleaseVerificationTests(unittest.TestCase):
    def test_private_verifier_rejects_other_hosts_before_getting_identity(self):
        with patch.dict(os.environ,{'CHECK_URL':'https://evil.example'}),patch('scripts.invoke_message_release_check.subprocess.run') as run:
            with self.assertRaises(ValueError):invoke_message_release_check.main()
            run.assert_not_called()

    def test_private_verifier_saves_safe_fields_without_identity_token(self):
        payload={'exit_code':1,'rows':[{'kind':'result','status':'failed','phase':'login','token':'private-token'}]}
        response=Mock();response.__enter__=Mock(return_value=io.StringIO(json.dumps(payload)));response.__exit__=Mock(return_value=False)
        opener=Mock();opener.open.return_value=response
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'CHECK_URL':'https://message-review-check-123-abc-du.a.run.app'}),patch('scripts.invoke_message_release_check.subprocess.run',return_value=Mock(stdout='private-token')),patch('scripts.invoke_message_release_check.urllib.request.build_opener',return_value=opener),contextlib.redirect_stdout(io.StringIO()):
            old=os.getcwd()
            try:
                os.chdir(directory);self.assertEqual(invoke_message_release_check.main(),1)
                text=(Path('release-check')/'verification.json').read_text()
                self.assertIn('login',text);self.assertNotIn('private-token',text)
            finally:os.chdir(old)

    def test_browser_only_allows_own_review_workflow_and_public_kakao_gets(self):
        for path,method in [('/control/messages','GET'),('/assets/file.js','GET'),('/internal/v1/admin/access','POST'),
            ('/internal/v1/message-records','POST'),('/internal/v1/message-records/manual-'+'a'*32+'/analyze','POST')]:
            self.assertTrue(allowed_request('https://keco-safety-map.web.app'+path,method))
        self.assertTrue(allowed_request('https://map0.daumcdn.net/map_2d_hd/tiles.png','GET'))
        for url,method in [('https://keco-safety-map.web.app/internal/v1/dispatch','POST'),
            ('https://keco-safety-map.web.app/api/v1/monitoring/refresh','POST'),
            ('https://keco-safety-map.web.app/internal/v1/message-records/feed','POST'),
            ('https://evil.example/internal/v1/admin/access','POST'),
            ('https://dapi.kakao.com/api','POST'),('https://evil.kakao.com.evil.example/a','GET'),
            ('http://keco-safety-map.web.app/control/messages','GET'),('https://user:password@keco-safety-map.web.app/a','GET'),
            ('https://keco-safety-map.web.app:wrong/a','GET')]:
            self.assertFalse(allowed_request(url,method))

    def test_missing_configuration_fails_before_browser_launch_without_printing_secret(self):
        with patch.dict(os.environ,{'ADMIN_ACCESS_PASSWORD':'private-password','VERIFY_APP_REVISION':'invalid'},clear=True),contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(ValueError):verify()
            self.assertNotIn('private-password',output.getvalue())

    def test_baseline_retains_only_fixed_service_revision_metadata_and_not_access_token(self):
        service={'status':{'latestReadyRevisionName':'old-revision','traffic':[{'revisionName':'old-revision','percent':100}]},'spec':{'template':{'spec':{'containers':[{'image':'old-image'}]}}}}
        run=Mock(side_effect=[Mock(returncode=0,stdout=json.dumps(service))]*2+[Mock(returncode=0,stdout='private-token')])
        hosting=Mock();hosting.__enter__=Mock(return_value=io.StringIO(json.dumps({'releases':[{'name':'release','version':{'name':'version'},'releaseUser':{'email':'private-email'}}]})));hosting.__exit__=Mock(return_value=False)
        with tempfile.TemporaryDirectory() as directory,patch('scripts.capture_release_baseline.subprocess.run',run),patch('scripts.capture_release_baseline.urllib.request.urlopen',return_value=hosting),contextlib.redirect_stdout(io.StringIO()):
            old=os.getcwd()
            try:
                os.chdir(directory);capture_release_baseline.main();text=(Path('release-check')/'baseline.json').read_text()
                self.assertNotIn('private',text);self.assertIn('old-revision',text)
                self.assertEqual(json.loads(text)['hosting']['version'],'version')
            finally:os.chdir(old)

    def test_failed_execution_with_empty_cli_output_still_collects_own_tagged_logs(self):
        payload=[{'jsonPayload':{'kind':'checkpoint','record_id':'manual-'+'b'*32}},
                 {'jsonPayload':{'kind':'result','status':'failed','phase':'login','error_type':'Error','password':'private'}}]
        run=Mock(return_value=Mock(returncode=0,stdout=json.dumps(payload)))
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'CHECK_JOB':'message-review-check-123'}),patch('scripts.collect_message_release_check.subprocess.run',run),contextlib.redirect_stdout(io.StringIO()):
            old=os.getcwd()
            try:
                os.chdir(directory);out=Path('release-check');out.mkdir();(out/'execution.json').write_text('')
                collect_message_release_check.main()
                report=json.loads((out/'verification.json').read_text())
                self.assertEqual(report['browser']['phase'],'login')
                self.assertEqual(report['record_id'],'manual-'+'b'*32)
                self.assertNotIn('private',json.dumps(report))
                self.assertIn('job_name="message-review-check-123"',run.call_args.args[0][3])
            finally:os.chdir(old)

    def test_scoped_log_collection_omits_unexpected_fields_and_keeps_no_credentials(self):
        payload=[{'jsonPayload':{'kind':'result','status':'passed','record_id':'manual-'+'a'*32,'token':'private-token'}},
                 {'jsonPayload':{'kind':'screenshot','name':'desktop','jpeg_base64':base64.b64encode(b'\xff\xd8fakejpeg').decode()}}]
        run=Mock(return_value=Mock(returncode=0,stdout=json.dumps(payload)))
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'CHECK_JOB':'message-review-check-123'}),patch('scripts.collect_message_release_check.subprocess.run',run),contextlib.redirect_stdout(io.StringIO()):
            old=os.getcwd()
            try:
                os.chdir(directory);out=Path('release-check');out.mkdir();(out/'execution.json').write_text(json.dumps({'metadata':{'name':'execution-123'},'status':{'conditions':[]}}))
                collect_message_release_check.main()
                self.assertNotIn('private',(out/'verification.json').read_text());self.assertTrue((out/'desktop.jpg').exists())
                self.assertIn('execution-123',run.call_args.args[0][3])
            finally:os.chdir(old)
