import pytest
import os
from unittest.mock import patch, MagicMock
from neon_link.cli import main

def test_cli_no_channels(monkeypatch):
	monkeypatch.setenv("ENABLE_TELEGRAM", "false")
	monkeypatch.setenv("ENABLE_FIREBASE", "false")
	with pytest.raises(SystemExit) as exc_info:
		main()
	assert exc_info.value.code == 1

@patch("neon_link.core.manager.PluginManager")
@patch("neon_link.core.crypto.IdentityManager")
@patch("neon_link.core.webhook.WebhookNotifier")
@patch("asyncio.get_event_loop")
def test_cli_both_channels(mock_loop, mock_wh, mock_id, mock_pm, monkeypatch):
	monkeypatch.setenv("ENABLE_TELEGRAM", "true")
	monkeypatch.setenv("ENABLE_FIREBASE", "true")
	
	with patch("neon_link.plugins.telegram.TelegramHub") as mock_th, \
		 patch("neon_link.plugins.firebase.FirebaseHub") as mock_fh, \
		 patch("time.sleep", side_effect=KeyboardInterrupt):
		from unittest.mock import AsyncMock
		mock_pm.return_value.start_all = AsyncMock()
		mock_pm.return_value.stop_all = AsyncMock()
		main()
		mock_pm.return_value.register.assert_any_call(mock_th.return_value)
		mock_pm.return_value.register.assert_any_call(mock_fh.return_value)
		mock_pm.return_value.start_all.assert_called_once()
		mock_pm.return_value.stop_all.assert_called_once()

def test_cli_exceptions():
	import neon_link.cli as cli
	from unittest.mock import patch
	import os
	
	with patch.dict(os.environ, {"ENABLE_TELEGRAM": "true", "ENABLE_FIREBASE": "true"}):
		with patch("neon_link.plugins.telegram.TelegramHub", side_effect=Exception("error")):
			with patch("neon_link.plugins.firebase.FirebaseHub", side_effect=Exception("error")):
				import pytest
				with pytest.raises(SystemExit):
					cli.main()

def test_cli_keyboard_interrupt():
	import neon_link.cli as cli
	from unittest.mock import patch
	import os
	with patch.dict(os.environ, {"ENABLE_TELEGRAM": "true", "ENABLE_FIREBASE": "false"}):
		with patch("neon_link.plugins.telegram.TelegramHub"):
			with patch("neon_link.cli.time.sleep", side_effect=KeyboardInterrupt()):
				with patch("neon_link.cli.asyncio.get_event_loop") as m_loop:
					cli.main()
					m_loop.return_value.run_until_complete.assert_called()
