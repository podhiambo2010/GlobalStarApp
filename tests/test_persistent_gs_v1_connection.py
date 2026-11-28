"""Test private local Streamlit secrets configuration without live DB calls."""
import os
from unittest import TestCase
from unittest.mock import patch

from supabase_compare_ui_v1 import _configured_readonly_dsn


class PersistentConnectionConfigurationTests(TestCase):
    def test_env_override_still_supported(self):
        with patch.dict(os.environ, {"GS_V1_READONLY_DSN": "temporary-readonly-connection"}):
            self.assertEqual(_configured_readonly_dsn(), "temporary-readonly-connection")

    @patch("supabase_compare_ui_v1.st.secrets")
    def test_stored_private_secret_used_after_restart(self, secrets):
        secrets.get.return_value = "permanent-private-connection"
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_configured_readonly_dsn(), "permanent-private-connection")

    @patch("supabase_compare_ui_v1.st.secrets")
    def test_missing_secret_fails_closed(self, secrets):
        secrets.get.return_value = ""
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_configured_readonly_dsn(), "")
