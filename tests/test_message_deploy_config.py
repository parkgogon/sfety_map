import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build_message_review_deploy_config import build_config, main


class MessageDeployConfigTests(unittest.TestCase):
    def test_default_does_not_enable_paid_provider_or_official_feed_bindings(self):
        self.assertEqual(build_config({}),{'MESSAGE_REVIEW_SECRET_BINDINGS':'','MESSAGE_REVIEW_ENV_VARS':'MESSAGE_REVIEW_STORE=firestore'})

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
