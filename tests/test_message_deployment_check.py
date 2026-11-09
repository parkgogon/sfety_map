import contextlib
import copy
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.check_message_review_deployment import audit, delivery_metadata, gcloud_json, main, markdown, role_hint, KEYS

MEMBER = 'serviceAccount:runtime@sample-project.iam.gserviceaccount.com'


class MessageDeploymentCheckTests(unittest.TestCase):
    def test_owner_can_resolve_latest_to_numeric_version_without_reading_secret_payload(self):
        self.service['spec']['template']['spec']['containers'][0]['env'] += [
            {'name': 'TELEGRAM_ADMIN_CHAT_ID', 'valueFrom': {'secretKeyRef': {'name': 'TELEGRAM_CHAT_ID', 'key': 'latest'}}}]
        def query(args):
            if args[:3] == ['secrets', 'versions', 'describe']:
                return {'name':'projects/sample-project/secrets/TELEGRAM_CHAT_ID/versions/7', 'state':'ENABLED'}, ''
            return self.query(args)
        report = audit('sample-project', query=query, keys=('TELEGRAM_ADMIN_CHAT_ID',))
        row = report['secrets'][0]
        self.assertEqual(row['resolved_numeric_version'], '7')
        self.assertEqual(row['secret_name'], 'TELEGRAM_CHAT_ID')
        self.assertEqual(row['version_reference'], 'latest')
        self.assertEqual(report['boundaries']['secret_payloads_read'], 0)

    def test_delivery_preflight_reads_existing_metadata_without_exposing_plaintext_or_assuming_latest(self):
        calls = []
        def query(args):
            calls.append(args)
            if args[0] == 'scheduler':
                return {'state': 'ENABLED', 'schedule': '*/5 * * * *'}, ''
            service = copy.deepcopy(self.service)
            service['spec']['template']['spec']['containers'][0]['env'] += [
                {'name': 'TELEGRAM_BOT_TOKEN', 'valueFrom': {'secretKeyRef': {'name': 'TELEGRAM_BOT_TOKEN', 'key': 'latest'}}},
                {'name': 'TELEGRAM_USER_CHAT_ID', 'value': 'private-staff-chat'}]
            return service, ''
        report = delivery_metadata('sample-project', query=query)
        self.assertEqual(len(calls), 6)
        self.assertTrue(report['numeric_versions_require_confirmation'])
        self.assertEqual(report['telegram_references'][0]['version_reference'], 'latest')
        self.assertIsNone(report['telegram_references'][1]['secret_name'])
        self.assertNotIn('private', json.dumps(report))
        self.assertTrue(all(c[0] in {'run', 'scheduler'} and 'describe' in c for c in calls))

    def test_delivery_metadata_permission_denial_is_unverified(self):
        report = delivery_metadata('sample-project', query=lambda args: (None, 'permission_denied'))
        self.assertEqual(len(report['findings']), 6)
        self.assertTrue(report['numeric_versions_require_confirmation'])
        self.assertTrue(all(r['delivery_flags'] is None for r in report['services'].values()))

    def setUp(self):
        env = [{'name':key,'valueFrom':{'secretKeyRef':{'name':key,'key':'1'}}} for key in KEYS]
        env += [{'name':'ADMIN_ACCESS_PASSWORD','valueFrom':{'secretKeyRef':{'name':'admin-secret','key':'latest'}}},
                {'name':'GOOGLE_CLOUD_PROJECT','value':'sample-project'}, {'name':'APP_REVISION','value':'a'*40},
                {'name':'PRIVATE_CONTACT','value':'private-phone-and-token'}]
        self.service = {'spec':{'template':{'spec':{'serviceAccountName':MEMBER.split(':')[1],'containers':[{'env':env}]}}},
                        'status':{'conditions':[{'type':'Ready','status':'True'}]}}
        self.policy={'bindings':[{'role':'roles/datastore.user','members':[MEMBER]},
                                  {'role':'roles/secretmanager.secretAccessor','members':[MEMBER]}]}
        self.calls=[]

    def query(self,args):
        self.calls.append(args)
        if args[:3]==['run','services','describe']:return copy.deepcopy(self.service),''
        if args[:3]==['firestore','databases','describe']:return {'type':'FIRESTORE_NATIVE'},''
        if args[:2]==['projects','get-iam-policy']:return copy.deepcopy(self.policy),''
        if args[:3]==['secrets','versions','describe']:return {'state':'ENABLED','name':'private-unused-metadata'},''
        if args[:2]==['secrets','get-iam-policy']:return {'bindings':[]},''
        raise AssertionError('unapproved command')

    def check(self):return audit('sample-project',query=self.query,checked_at='fixed')

    def test_configured_metadata_still_labels_runtime_checks_unverified_and_never_queries_data(self):
        report=self.check()
        self.assertTrue(report['audit_complete']);self.assertEqual(report['findings'],[])
        self.assertEqual(report['firestore']['runtime_read_write'],'not_tested')
        self.assertEqual(report['firestore']['iam_hint'],'allow_binding_found')
        self.assertTrue(all(s['iam_hint']=='allow_binding_found' for s in report['secrets']))
        self.assertEqual(len(self.calls),9)
        self.assertNotIn('private',json.dumps(report));self.assertNotIn('private',markdown(report))
        self.assertTrue(all('access' not in c and 'create' not in c and 'deploy' not in c for c in self.calls))
        self.assertEqual(set(report['boundaries'].values()),{0})

    def test_available_secrets_without_cloud_run_bindings_are_reported_as_missing(self):
        self.service['spec']['template']['spec']['containers'][0]['env']=[{'name':'GOOGLE_CLOUD_PROJECT','value':'sample-project'}]
        report=self.check()
        self.assertTrue(report['audit_complete'])
        self.assertTrue(all(s['binding']=='missing' and s['version_state']=='ENABLED' for s in report['secrets']))
        self.assertIn('OPENAI_API_KEY_binding_missing',report['findings']);self.assertIn('admin_auth_missing',report['findings'])

    def test_plaintext_key_presence_is_detected_without_printing_value(self):
        self.service['spec']['template']['spec']['containers'][0]['env'][0]={'name':'OPENAI_API_KEY','value':'private-secret-value'}
        report=self.check()
        self.assertEqual(report['secrets'][0]['binding'],'plaintext_present')
        self.assertNotIn('private-secret-value',json.dumps(report)+markdown(report))

    def test_unavailable_service_metadata_does_not_claim_keys_are_missing(self):
        def query(args):return (None,'permission_denied') if args[0]=='run' else self.query(args)
        report=audit('sample-project',query=query)
        self.assertFalse(report['audit_complete']);self.assertIsNone(report['configuration']['message_store_firestore'])
        self.assertTrue(all(s['binding']=='unverified' for s in report['secrets']))
        self.assertNotIn('OPENAI_API_KEY_binding_missing',report['findings'])

    def test_secret_permission_denial_is_unverified_instead_of_false_absence(self):
        def query(args):return (None,'permission_denied') if args[:3]==['secrets','versions','describe'] else self.query(args)
        report=audit('sample-project',query=query)
        self.assertFalse(report['audit_complete']);self.assertTrue(all(s['version_state']=='unverified' for s in report['secrets']))
        self.assertTrue(all(s['metadata_status']=='permission_denied' for s in report['secrets']))

    def test_disabled_version_and_non_native_store_are_findings_without_changing_them(self):
        def query(args):
            if args[:3]==['secrets','versions','describe']:return {'state':'DISABLED'},''
            if args[0]=='firestore':return {'type':'DATASTORE_MODE'},''
            return self.query(args)
        report=audit('sample-project',query=query)
        self.assertIn('firestore_native_database_required',report['findings'])
        self.assertIn('OPENAI_API_KEY_version_unverified',report['findings'])

    def test_conditional_or_custom_roles_are_not_claimed_to_prove_runtime_access(self):
        self.assertEqual(role_hint({'bindings':[{'role':'roles/datastore.user','members':[MEMBER],'condition':{'expression':'true'}}]},MEMBER,{'roles/datastore.user'}),'unverified')
        self.assertEqual(role_hint({'bindings':[{'role':'projects/x/roles/custom','members':[MEMBER]}]},MEMBER,{'roles/datastore.user'}),'unverified')

    def test_cross_project_or_unexpected_references_are_not_followed(self):
        self.service['spec']['template']['spec']['containers'][0]['env'][0]['valueFrom']['secretKeyRef']['name']='projects/other/secrets/private'
        report=self.check()
        self.assertEqual(report['secrets'][0]['metadata_status'],'external_or_unsupported_reference')
        self.assertFalse(report['audit_complete']);self.assertEqual(len(self.calls),7)

    def test_nonpersistent_store_different_model_and_unready_service_require_attention(self):
        self.service['spec']['template']['spec']['containers'][0]['env'] += [{'name':'MESSAGE_REVIEW_STORE','value':'memory'}, {'name':'OPENAI_MODEL','value':'private-other-model'}, {'name':'OPENAI_REASONING_EFFORT','value':'high'}]
        self.service['status']['conditions']=[]
        report=self.check()
        for finding in ['persistent_message_store_required','model_differs_from_evaluation','reasoning_differs_from_evaluation','cloud_run_not_ready']:self.assertIn(finding,report['findings'])
        self.assertNotIn('private-other-model',json.dumps(report))

    def test_invalid_project_is_rejected_before_subprocess_or_file_creation(self):
        with self.assertRaises(ValueError):audit('bad; secret access',query=Mock(side_effect=AssertionError()))
        with tempfile.TemporaryDirectory() as directory,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--project','','--output-dir',directory]),2)
            self.assertEqual(list(Path(directory).iterdir()),[])

    def test_command_failures_and_timeout_do_not_leak_stderr_or_tokens(self):
        for error,expected in [('PERMISSION_DENIED private-token','permission_denied'),('NOT_FOUND private-token','not_found'),('private-token','unavailable')]:
            with patch('scripts.check_message_review_deployment.subprocess.run',return_value=Mock(returncode=1,stderr=error)) as run:
                value=gcloud_json(['secrets','versions','describe','1','--secret','test','--project','sample-project'])
                self.assertEqual(value,(None,expected));self.assertEqual(run.call_args.kwargs['timeout'],25)
                self.assertNotIn('private-token',str(value))
        with patch('scripts.check_message_review_deployment.subprocess.run',side_effect=subprocess.TimeoutExpired('gcloud',25,stderr='private-token')):
            self.assertEqual(gcloud_json([]),(None,'unavailable'))

    def test_cli_writes_only_sanitized_summary_and_report_and_returns_incomplete_status(self):
        report=self.check()
        with tempfile.TemporaryDirectory() as directory,patch('scripts.check_message_review_deployment.audit',return_value=report),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--project','sample-project','--output-dir',directory]),0)
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()),['report.json','summary.md'])
            self.assertEqual(json.loads((Path(directory)/'report.json').read_text()),report)
            report['audit_complete']=False
            self.assertEqual(main(['--project','sample-project','--output-dir',directory]),1)
