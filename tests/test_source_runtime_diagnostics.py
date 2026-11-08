import datetime as dt
import json
import unittest
from unittest.mock import patch,Mock
import ssl
import urllib3.util.connection
from scripts.diagnose_sources_runtime import page_summary,exception_summary,trace_connection
from safety_dashboard.application.context_info import KST

class SourceRuntimeDiagnosticTests(unittest.TestCase):
    def test_shape_report_does_not_export_text_ids_or_recipient_details(self):
        payload={'body':[{'SN':'private-id','MSG_CN':'private-message-with-sufficient-length','CRT_DT':'2026-11-08 12:00:00','RCPTN_RGN_NM':'부산광역시_비공개동'}],'totalCount':1}
        result=page_summary(payload,dt.date(2026,11,8),dt.date(2026,11,8),'2026-11-08T13:00:00+09:00')
        self.assertEqual(result['reasons']['unrecognized_recipient'],1)
        self.assertEqual(result['reasons']['skipped_before_start'],1)
        for private in ('private','비공개동'):self.assertNotIn(private,json.dumps(result,ensure_ascii=False))

    def test_exception_chain_retains_types_and_codes_but_never_exception_strings(self):
        error=ConnectionError('https://private-key',OSError(111,'private-payload'))
        result=exception_summary(error)
        self.assertIn('ConnectionError',result['exception_types'])
        self.assertIn(111,result['errno'])
        self.assertNotIn('private',json.dumps(result))

    def test_tcp_and_tls_are_separate_and_wrappers_are_restored_without_error_messages(self):
        stages=[]
        with patch('urllib3.util.connection.create_connection',return_value=Mock()) as connect,patch('ssl.SSLContext.wrap_socket',side_effect=TimeoutError('private-key')) as wrap:
            with self.assertRaises(TimeoutError),trace_connection(stages):
                urllib3.util.connection.create_connection(('host',443))
                ssl.SSLContext.wrap_socket(Mock())
            self.assertIs(urllib3.util.connection.create_connection,connect)
            self.assertIs(ssl.SSLContext.wrap_socket,wrap)
        self.assertEqual([(i['stage'],i['success']) for i in stages],[('tcp',True),('tls',False)])
        self.assertNotIn('private',json.dumps(stages))
