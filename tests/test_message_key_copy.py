import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.copy_message_api_keys import copy_keys, main, markdown, PROJECT_NUMBER

ROOT = Path(__file__).resolve().parents[1]
VALUES = {'OPENAI_API_KEY':'private-openai-fixture','KAKAO_REST_API_KEY':'private-kakao-fixture'}


def response(name, version=1):
    return Mock(returncode=0,stdout=f'projects/{PROJECT_NUMBER}/secrets/{name}/versions/{version}\n',stderr='')


class MessageKeyCopyTests(unittest.TestCase):
    def test_dry_run_never_reads_or_uploads_keys(self):
        run=Mock(side_effect=AssertionError('must not call gcloud'))
        report=copy_keys({},run=run)
        self.assertFalse(report['executed']);self.assertTrue(all(r['status']=='not_attempted' for r in report['results']))
        run.assert_not_called()

    def test_copy_uses_stdin_and_fixed_project_without_raw_values_in_args_child_env_or_report(self):
        run=Mock(side_effect=[response('OPENAI_API_KEY'),response('KAKAO_REST_API_KEY',2)])
        original={**VALUES,'GOOGLE_APPLICATION_CREDENTIALS':'credential-selector','CLOUDSDK_CORE_LOG_HTTP':'true'}
        report=copy_keys(original,execute=True,run=run)
        self.assertEqual([r['version'] for r in report['results']],['1','2'])
        self.assertEqual(original['OPENAI_API_KEY'],VALUES['OPENAI_API_KEY'])
        for call,name in zip(run.call_args_list,VALUES):
            argv=call.args[0];kw=call.kwargs
            self.assertEqual(argv[:5],['gcloud','secrets','versions','add',name])
            self.assertEqual(argv[argv.index('--project')+1],'keco-safety-map')
            self.assertIn('--data-file=-',argv);self.assertEqual(kw['input'],VALUES[name]);self.assertEqual(kw['timeout'],40)
            self.assertNotIn('private',str(argv)+str(kw['env']))
            self.assertEqual(kw['env']['GOOGLE_APPLICATION_CREDENTIALS'],'credential-selector')
            self.assertEqual(kw['env']['CLOUDSDK_CORE_MAX_HTTP_RETRIES'],'0')
            self.assertEqual(kw['env']['CLOUDSDK_CORE_LOG_HTTP'],'false')
            self.assertEqual(kw['env']['CLOUDSDK_CORE_DISABLE_FILE_LOGGING'],'true')
        self.assertNotIn('private',json.dumps(report)+markdown(report))

    def test_missing_or_invalid_key_blocks_all_writes_before_first_upload(self):
        for values in ({'OPENAI_API_KEY':'private-fixture'}, {**VALUES,'KAKAO_REST_API_KEY':' '},
                       {**VALUES,'OPENAI_API_KEY':'a\nb'}, {**VALUES,'OPENAI_API_KEY':'a'*4097}):
            run=Mock()
            with self.assertRaises(ValueError) as error:copy_keys(values,execute=True,run=run)
            self.assertNotIn('private-fixture',str(error.exception));run.assert_not_called()

    def test_single_key_retry_never_creates_another_version_of_other_key(self):
        for target,key in [('openai','OPENAI_API_KEY'),('kakao','KAKAO_REST_API_KEY')]:
            run=Mock(return_value=response(key,2));report=copy_keys({key:VALUES[key]},target,execute=True,run=run)
            self.assertEqual(len(report['results']),1);self.assertEqual(report['results'][0]['secret'],key)
            run.assert_called_once()
        with self.assertRaises(ValueError):copy_keys(VALUES,'other',execute=True)

    def test_partial_failure_keeps_created_version_and_never_retries_or_logs_errors(self):
        run=Mock(side_effect=[response('OPENAI_API_KEY'),Mock(returncode=1,stderr='PERMISSION_DENIED private-kakao-fixture',stdout='')])
        report=copy_keys(VALUES,execute=True,run=run)
        self.assertEqual([r['status'] for r in report['results']],['version_created','request_denied'])
        self.assertEqual(report['results'][0]['version'],'1');self.assertEqual(run.call_count,2)
        self.assertNotIn('private',json.dumps(report)+markdown(report))

    def test_timeout_and_ambiguous_failures_stop_remaining_writes_without_automatic_retry(self):
        for failure in [subprocess.TimeoutExpired('gcloud',40,output='private-fixture'),OSError('private-fixture'),
                        Mock(returncode=1,stdout='',stderr='private-error')]:
            run=Mock(side_effect=failure) if isinstance(failure,Exception) else Mock(return_value=failure)
            report=copy_keys(VALUES,execute=True,run=run)
            self.assertEqual([r['status'] for r in report['results']],['outcome_unknown','not_attempted'])
            self.assertNotIn('private',json.dumps(report));run.assert_called_once()

    def test_wrong_project_secret_or_untrusted_response_is_never_published(self):
        for text in ['projects/other/secrets/OPENAI_API_KEY/versions/1',f'projects/{PROJECT_NUMBER}/secrets/OTHER/versions/1','private-raw-response']:
            run=Mock(return_value=Mock(returncode=0,stdout=text,stderr=''))
            report=copy_keys(VALUES,execute=True,run=run)
            self.assertEqual(report['results'][0]['status'],'outcome_unknown');run.assert_called_once()
            self.assertNotIn(text,json.dumps(report))

    def test_cli_requires_execute_flag_and_writes_only_sanitized_metadata(self):
        with tempfile.TemporaryDirectory() as directory,contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['--output-dir',directory]),0)
            report=json.loads((Path(directory)/'report.json').read_text())
            self.assertFalse(report['executed'])
            with patch.dict(os.environ,VALUES,clear=True),patch('scripts.copy_message_api_keys.copy_keys',return_value=copy_keys(VALUES,execute=True,run=Mock(side_effect=[response('OPENAI_API_KEY'),response('KAKAO_REST_API_KEY')]))):
                self.assertEqual(main(['--execute','--output-dir',directory]),0)
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()),['report.json','summary.md'])
            self.assertNotIn('private',output.getvalue()+(Path(directory)/'report.json').read_text())
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{},clear=True),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--execute','--output-dir',directory]),2)
            self.assertEqual(list(Path(directory).iterdir()),[])


class MessageKeyBootstrapTests(unittest.TestCase):
    def run_bootstrap(self, *, denied=False):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);fake=root/'gcloud';log=root/'log.jsonl'
            fake.write_text('''#!/usr/bin/env python3
import os,sys,json
with open(os.environ['GCLOUD_TEST_LOG'],'a') as stream:stream.write(json.dumps(sys.argv[1:])+'\\n')
if sys.argv[1:3]==['secrets','describe']:raise SystemExit(1)
if os.environ.get('GCLOUD_TEST_CREATE_DENIED') and sys.argv[1:3]==['secrets','create']:raise SystemExit(1)
''')
            fake.chmod(0o700)
            result=subprocess.run(['bash',str(ROOT/'scripts/prepare_message_key_secrets.sh')],capture_output=True,text=True,
                env={**os.environ,'PATH':str(root)+os.pathsep+os.environ['PATH'],'GCLOUD_TEST_LOG':str(log),
                    'GCLOUD_TEST_CREATE_DENIED':'1' if denied else ''},timeout=10)
            calls=[json.loads(line) for line in log.read_text().splitlines()]
            return result,calls

    def test_owner_bootstrap_creates_only_two_empty_secrets_and_scoped_expiring_writer_bindings(self):
        result,calls=self.run_bootstrap();self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(len(calls),8)
        for args in calls:
            self.assertEqual(args[0],'secrets');self.assertIn(args[2],VALUES)
            self.assertIn('--project=keco-safety-map',args)
            self.assertNotIn('access',args);self.assertNotIn('--data-file',str(args))
        bindings=[args for args in calls if args[1]=='add-iam-policy-binding']
        self.assertEqual(len(bindings),4)
        for args in bindings:
            if '--role=roles/secretmanager.secretVersionAdder' in args:
                self.assertIn('--member=serviceAccount:github-deployer@keco-safety-map.iam.gserviceaccount.com',args)
                self.assertTrue(any(a.startswith('--condition=expression=request.time < timestamp(') for a in args))
            else:
                self.assertIn('--role=roles/secretmanager.secretAccessor',args)
                self.assertIn('--member=serviceAccount:safety-dashboard-runtime@keco-safety-map.iam.gserviceaccount.com',args)
                self.assertIn('--condition=None',args)
        self.assertIn('등록 준비 완료',result.stdout)

    def test_failed_secret_creation_stops_before_any_iam_mutation(self):
        result,calls=self.run_bootstrap(denied=True)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual([a[1] for a in calls],['describe','create'])
        self.assertNotIn('등록 준비 완료',result.stdout)
