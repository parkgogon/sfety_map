import unittest
from unittest.mock import Mock, patch
import requests

from safety_dashboard.adapters.telegram import TelegramNotifier


class TelegramTransportTests(unittest.TestCase):
    def setUp(self):self.sender=TelegramNotifier('private-token','-100123')

    @patch('safety_dashboard.adapters.telegram.requests.post')
    def test_plain_text_confirmed_receipt_preserves_message_id_and_disables_redirects(self,post):
        post.return_value=Mock(status_code=200,json=Mock(return_value={'ok':True,'result':{'message_id':9,'chat':{'id':-100123}}}))
        result=self.sender.send_once('<b>원문 & 검증한 안내</b>')
        self.assertEqual((result.state,result.message_id),('sent',9))
        payload=post.call_args.kwargs
        self.assertFalse(payload['allow_redirects'])
        self.assertNotIn('parse_mode',payload['json'])
        self.assertEqual(payload['json']['text'],'<b>원문 & 검증한 안내</b>')
        self.assertEqual(post.call_count,1)

    @patch('safety_dashboard.adapters.telegram.requests.post')
    def test_only_explicit_error_envelopes_classify_as_known_rejections_or_retry(self,post):
        for code,state in ((400,'rejected'),(401,'rejected'),(403,'rejected'),(404,'rejected'),(429,'rate_limited'),(500,'unknown')):
            with self.subTest(code=code):
                post.return_value=Mock(status_code=code,json=Mock(return_value={'ok':False,'error_code':code,'description':'private-error','parameters':{'retry_after':30}}))
                result=self.sender.send_once('공식 안내')
                self.assertEqual(result.state,state)
                self.assertNotIn('private',str(result))
        self.assertEqual(post.call_count,6)

    @patch('safety_dashboard.adapters.telegram.requests.post')
    def test_timeout_redirect_invalid_or_wrong_chat_receipts_are_unknown_without_retry(self,post):
        for body,status in (({'ok':True,'result':{'message_id':4,'chat':{'id':-999}}},200),
                            ({'ok':True,'result':{}},200),({'ok':False,'error_code':500},500),({},302),([],200)):
            with self.subTest(body=body):
                post.return_value=Mock(status_code=status,json=Mock(return_value=body))
                self.assertEqual(self.sender.send_once('공식 안내').state,'unknown')
        post.side_effect=requests.Timeout('private-token')
        self.assertEqual(self.sender.send_once('공식 안내').state,'unknown')
        self.assertEqual(post.call_count,6)

    @patch('safety_dashboard.adapters.telegram.requests.post')
    def test_invalid_configuration_or_oversized_text_does_not_start_http(self,post):
        self.assertEqual(TelegramNotifier('','').send_once('내용').state,'rejected')
        self.assertEqual(self.sender.send_once('가'*3901).state,'rejected')
        post.assert_not_called()
