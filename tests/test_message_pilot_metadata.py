import json
import unittest
from scripts.capture_message_pilot import service_summary,job_summary

class PilotMetadataTests(unittest.TestCase):
    def test_only_approved_settings_and_secret_version_numbers_are_exported(self):
        source={'status':{'latestReadyRevisionName':'ready','traffic':[{'percent':100}]},'spec':{'template':{'spec':{'serviceAccountName':'runtime',
                'containers':[{'image':'image','env':[{'name':'APP_REVISION','value':'sha'},
                {'name':'ADMIN_ACCESS_PASSWORD','value':'private-password'},
                {'name':'OPENAI_API_KEY','value':'private-key'},
                {'name':'SAFETY_DATA_API_KEY','valueFrom':{'secretKeyRef':{'name':'SAFETY_DATA_API_KEY','key':'1'}}}]}]}}}}
        result=service_summary(source)
        self.assertEqual(result['settings'],{'APP_REVISION':'sha'})
        self.assertEqual(result['message_secret_versions'],{'SAFETY_DATA_API_KEY':'1'})
        self.assertNotIn('private',json.dumps(result))

    def test_scheduler_metadata_does_not_export_body_headers_or_tokens(self):
        result=job_summary({'state':'ENABLED','schedule':'* * * * *','httpTarget':{'uri':'https://worker/internal/v1/collect','body':'private-body',
            'headers':{'Authorization':'private-token'},'oidcToken':{'serviceAccountEmail':'scheduler','audience':'worker','token':'private-token'}}})
        self.assertEqual(result['oidc_account'],'scheduler')
        self.assertNotIn('private',json.dumps(result))
