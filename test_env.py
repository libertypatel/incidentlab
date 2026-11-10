"""Only recognized application settings are loaded; shell settings take priority."""
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch
from incidentlab import load_env


class EnvironmentTests(unittest.TestCase):
    def test_loads_model_and_paypal_settings_only(self):
        with tempfile.TemporaryDirectory() as folder:
            env_path = Path(folder) / '.env'
            env_path.write_text('PAYPAL_CLIENT_ID=fake-client\nINCIDENTLAB_LLM_URL=https://example.test/v1/chat/completions\nINCIDENTLAB_MODEL=fake-model\nINCIDENTLAB_LLM_KEY=fake-key\nUNRELATED_SETTING=ignored\n')
            with patch('incidentlab.Path', return_value=env_path), patch.dict(os.environ, {}, clear=True):
                load_env()
                self.assertEqual(os.environ['INCIDENTLAB_MODEL'], 'fake-model')
                self.assertEqual(os.environ['INCIDENTLAB_LLM_KEY'], 'fake-key')
                self.assertEqual(os.environ['PAYPAL_CLIENT_ID'], 'fake-client')
                self.assertNotIn('UNRELATED_SETTING', os.environ)

    def test_shell_value_takes_priority(self):
        with tempfile.TemporaryDirectory() as folder:
            env_path = Path(folder) / '.env'
            env_path.write_text('INCIDENTLAB_MODEL=file-model\n')
            with patch('incidentlab.Path', return_value=env_path), patch.dict(os.environ, {'INCIDENTLAB_MODEL': 'shell-model'}, clear=True):
                load_env()
                self.assertEqual(os.environ['INCIDENTLAB_MODEL'], 'shell-model')
