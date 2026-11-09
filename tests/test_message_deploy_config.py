import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build_message_review_deploy_config import build_config, main
from safety_dashboard.application.message_automation import MessageAutomationSettings


class MessageDeployConfigTests(unittest.TestCase):
    def test_stage_three_flags_are_opt_in_and_cost_defaults_are_visible(self):
        settings=MessageAutomationSettings.from_environment({})
        self.assertFalse(settings.latest_first_enabled)
        self.assertFalse(settings.spend_budget_enabled)
        self.assertFalse(settings.emergency_fallback_enabled)
        config=build_config({})['MESSAGE_REVIEW_ENV_VARS']
        self.assertIn('MESSAGE_COLLECTION_FAST_ENABLED=false',config)
        self.assertIn('MESSAGE_AI_SPEND_BUDGET_ENABLED=false',config)
        self.assertIn('MESSAGE_EMERGENCY_FALLBACK_ENABLED=false',config)
        self.assertIn('MESSAGE_AI_DAILY_BUDGET_CENTS=100',config)
        self.assertIn('MESSAGE_AI_MONTHLY_BUDGET_CENTS=2000',config)

    def test_latest_mode_and_cost_values_match_runtime_and_deployment_validation(self):
        env={'MESSAGE_COLLECTION_FAST_ENABLED':'true','MESSAGE_AI_SPEND_BUDGET_ENABLED':'true',
             'MESSAGE_AI_DAILY_BUDGET_CENTS':'150','MESSAGE_AI_MONTHLY_BUDGET_CENTS':'3000',
             'MESSAGE_NOTIFICATION_PREPARATION_ENABLED':'true','MESSAGE_EMERGENCY_FALLBACK_ENABLED':'true'}
        settings=MessageAutomationSettings.from_environment(env)
        config=build_config(env)['MESSAGE_REVIEW_ENV_VARS']
        self.assertEqual(settings.interval_seconds,300)
        self.assertEqual(settings.daily_budget_cents,150)
        self.assertEqual(settings.monthly_budget_cents,3000)
        self.assertIn('MESSAGE_COLLECTION_INTERVAL_MINUTES=5',config)
        for invalid in ({'MESSAGE_COLLECTION_FAST_ENABLED':'true','MESSAGE_COLLECTION_INTERVAL_MINUTES':'15'},
                        {'MESSAGE_COLLECTION_INTERVAL_MINUTES':'5'},
                        {'MESSAGE_AI_DAILY_BUDGET_CENTS':'1.5'},
                        {'MESSAGE_AI_DAILY_BUDGET_CENTS':'0'},
                        {'MESSAGE_AI_MONTHLY_BUDGET_CENTS':'-1'},
                        {'MESSAGE_EMERGENCY_FALLBACK_ENABLED':'true'}):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):MessageAutomationSettings.from_environment(invalid)
                with self.assertRaises(ValueError):build_config(invalid)

    def test_default_does_not_enable_paid_provider_or_official_feed_bindings(self):
        config=build_config({})
        self.assertEqual(config['MESSAGE_REVIEW_SECRET_BINDINGS'],'')
        self.assertIn('MESSAGE_REVIEW_STORE=firestore',config['MESSAGE_REVIEW_ENV_VARS'])
        self.assertIn('MESSAGE_COLLECTION_ENABLED=false',config['MESSAGE_REVIEW_ENV_VARS'])
        self.assertIn('MESSAGE_ANALYSIS_DAILY_LIMIT=20',config['MESSAGE_REVIEW_ENV_VARS'])

    def test_enabled_ai_requires_both_fixed_versions_and_evaluated_model(self):
        config=build_config({'MESSAGE_REVIEW_AI_ENABLED':'true','MESSAGE_REVIEW_OPENAI_VERSION':'2','MESSAGE_REVIEW_KAKAO_VERSION':'7'})
        self.assertEqual(config['MESSAGE_REVIEW_SECRET_BINDINGS'],'OPENAI_API_KEY=OPENAI_API_KEY:2,KAKAO_REST_API_KEY=KAKAO_REST_API_KEY:7')
        self.assertIn('OPENAI_MODEL=gpt-5.4-mini-2026-03-17',config['MESSAGE_REVIEW_ENV_VARS'])
        self.assertIn('OPENAI_REASONING_EFFORT=low',config['MESSAGE_REVIEW_ENV_VARS'])
        self.assertNotIn('SAFETY_DATA',str(config))
        for versions in ({},{'MESSAGE_REVIEW_OPENAI_VERSION':'1'}):
            with self.assertRaises(ValueError):build_config({'MESSAGE_REVIEW_AI_ENABLED':'true',**versions})

    def test_official_feed_can_be_enabled_independently_and_all_bindings_combine(self):
        config=build_config({'MESSAGE_REVIEW_FEED_ENABLED':'true','MESSAGE_REVIEW_FEED_VERSION':'3'})
        self.assertEqual(config['MESSAGE_REVIEW_SECRET_BINDINGS'],'SAFETY_DATA_API_KEY=SAFETY_DATA_API_KEY:3')
        config=build_config({'MESSAGE_REVIEW_AI_ENABLED':'true','MESSAGE_REVIEW_OPENAI_VERSION':'1','MESSAGE_REVIEW_KAKAO_VERSION':'2',
            'MESSAGE_REVIEW_FEED_ENABLED':'true','MESSAGE_REVIEW_FEED_VERSION':'3'})
        self.assertEqual(len(config['MESSAGE_REVIEW_SECRET_BINDINGS'].split(',')),3)

    def test_unvalidated_values_cannot_inject_shell_or_github_env_configuration(self):
        for value in ['latest','0','-1','1,OTHER=x','1\nOTHER=x','$(private-token)','1:latest','1'*20]:
            with self.assertRaises(ValueError) as error:build_config({'MESSAGE_REVIEW_FEED_ENABLED':'true','MESSAGE_REVIEW_FEED_VERSION':value})
            self.assertNotIn(value,str(error.exception))
        with self.assertRaises(ValueError):build_config({'MESSAGE_REVIEW_AI_ENABLED':'True'})

    def test_helper_does_not_read_raw_keys_or_copy_them_into_environment_file(self):
        env={'OPENAI_API_KEY':'private-key','KAKAO_REST_API_KEY':'private-place','SAFETY_DATA_API_KEY':'private-feed'}
        self.assertNotIn('private',str(build_config(env)))
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,env,clear=True),contextlib.redirect_stdout(io.StringIO()):
            p=Path(directory)/'github-env';p.write_text('EXISTING=keep\n')
            self.assertEqual(main(['--github-env',str(p)]),0)
            self.assertTrue(p.read_text().startswith('EXISTING=keep\n'))
            self.assertNotIn('private',p.read_text())

    def test_invalid_configuration_exits_before_changing_github_environment(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'MESSAGE_REVIEW_AI_ENABLED':'true'},clear=True),contextlib.redirect_stdout(io.StringIO()) as output:
            p=Path(directory)/'env';p.write_text('EXISTING=keep\n')
            self.assertEqual(main(['--github-env',str(p)]),2)
            self.assertEqual(p.read_text(),'EXISTING=keep\n')
            self.assertIn('MESSAGE_REVIEW_OPENAI_VERSION',output.getvalue())

    def test_live_delivery_is_off_by_default_and_requires_independent_flags_and_pinned_existing_rooms(self):
        self.assertFalse(MessageAutomationSettings.from_environment({}).delivery_enabled)
        self.assertEqual(build_config({})['MESSAGE_DELIVERY_SECRET_BINDINGS'],'')
        env={'MESSAGE_COLLECTION_ENABLED':'true','MESSAGE_COLLECTION_CONTRACT_VERIFIED':'true',
             'MESSAGE_REVIEW_AI_ENABLED':'true','MESSAGE_REVIEW_OPENAI_VERSION':'1','MESSAGE_REVIEW_KAKAO_VERSION':'1',
             'MESSAGE_REVIEW_FEED_ENABLED':'true','MESSAGE_REVIEW_FEED_VERSION':'1','MESSAGE_COLLECTION_FAST_ENABLED':'true',
             'MESSAGE_AI_SPEND_BUDGET_ENABLED':'true','MESSAGE_NOTIFICATION_PREPARATION_ENABLED':'true',
             'MESSAGE_EMERGENCY_FALLBACK_ENABLED':'true','MESSAGE_DELIVERY_ENABLED':'true',
             'MESSAGE_DELIVERY_BOT_VERSION':'1','MESSAGE_DELIVERY_STAFF_VERSION':'2','MESSAGE_DELIVERY_ADMIN_VERSION':'3'}
        config=build_config(env)
        self.assertEqual(config['MESSAGE_DELIVERY_SECRET_BINDINGS'],
            'TELEGRAM_BOT_TOKEN=TELEGRAM_BOT_TOKEN:1,TELEGRAM_USER_CHAT_ID=TELEGRAM_USER_CHAT_ID:2,TELEGRAM_ADMIN_CHAT_ID=TELEGRAM_CHAT_ID:3')
        self.assertNotIn('TELEGRAM',config['MESSAGE_REVIEW_SECRET_BINDINGS'])
        self.assertTrue(MessageAutomationSettings.from_environment(env).delivery_enabled)
        for changes in ({'MESSAGE_AI_SPEND_BUDGET_ENABLED':'false'},{'MESSAGE_COLLECTION_ENABLED':'false'},
                        {'MESSAGE_DELIVERY_STAFF_VERSION':'latest'},{'TELEGRAM_ADMIN_SECRET_NAME':'unvalidated,SECRET'}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):build_config({**env,**changes})
