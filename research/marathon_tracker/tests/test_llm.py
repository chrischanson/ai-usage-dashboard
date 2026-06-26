import unittest
from unittest.mock import patch, MagicMock
import os
import json
import subprocess

from marathon_tracker.llm import extract_with_llm, resolve_official_url, resolve_event_webpage

class TestLlm(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_extract_with_llm_success(self, mock_urlopen):
        # Setup mock response
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "choices": [{
                "message": {
                    "content": "```json\n{\n  \"event_date\": \"2027-04-25\",\n  \"registration_windows\": [],\n  \"confidence\": \"high\",\n  \"notes\": \"Mocked extract\",\n  \"raw_evidence\": []\n}\n```"
                }
            }]
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        # Set fake LLM_API_KEY environment variable
        with patch.dict(os.environ, {"LLM_API_KEY": "fake-key"}):
            res = extract_with_llm("London Marathon", "Some page text")
            self.assertIsNotNone(res)
            self.assertEqual(res.get("event_date"), "2027-04-25")
            self.assertEqual(res.get("confidence"), "high")
            self.assertEqual(res.get("notes"), "Mocked extract")

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_extract_with_llm_cli_agy_success(self, mock_run, mock_which):
        # Mock agy exists, opencode doesn't
        mock_which.side_effect = lambda cmd: "/usr/local/bin/agy" if cmd == "agy" else None

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "```json\n{\n  \"event_date\": \"2027-04-25\",\n  \"registration_windows\": [],\n  \"confidence\": \"high\",\n  \"notes\": \"Mocked CLI agy\",\n  \"raw_evidence\": []\n}\n```"
        mock_run.return_value = mock_result

        with patch.dict(os.environ, {}, clear=True):
            res = extract_with_llm("London Marathon", "Some page text")
            self.assertIsNotNone(res)
            self.assertEqual(res.get("event_date"), "2027-04-25")
            self.assertEqual(res.get("notes"), "Mocked CLI agy")
            mock_run.assert_called_once()
            self.assertEqual(mock_run.call_args[0][0][0], "agy")

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_extract_with_llm_cli_opencode_success(self, mock_run, mock_which):
        # Mock agy doesn't exist, opencode does
        mock_which.side_effect = lambda cmd: "/usr/local/bin/opencode" if cmd == "opencode" else None

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "> build · deepseek-v4-flash-free\n\n{\n  \"event_date\": \"2027-04-25\",\n  \"registration_windows\": [],\n  \"confidence\": \"medium\",\n  \"notes\": \"Mocked CLI opencode\",\n  \"raw_evidence\": []\n}"
        mock_run.return_value = mock_result

        with patch.dict(os.environ, {}, clear=True):
            res = extract_with_llm("London Marathon", "Some page text")
            self.assertIsNotNone(res)
            self.assertEqual(res.get("event_date"), "2027-04-25")
            self.assertEqual(res.get("notes"), "Mocked CLI opencode")
            mock_run.assert_called_once()
            self.assertEqual(mock_run.call_args[0][0][0], "opencode")

    @patch("shutil.which")
    def test_extract_with_llm_no_key_and_no_cli(self, mock_which):
        # Mock no CLIs exist
        mock_which.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            res = extract_with_llm("London Marathon", "Some page text")
            self.assertIsNone(res)

    @patch("urllib.request.urlopen")
    def test_resolve_event_webpage_success(self, mock_urlopen):
        # Setup mock response
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "choices": [{
                "message": {
                    "content": "https://copenhagenmarathon.dk/en/"
                }
            }]
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        # Set fake LLM_API_KEY environment variable
        with patch.dict(os.environ, {"LLM_API_KEY": "fake-key"}):
            res = resolve_event_webpage("Copenhagen Marathon", 2027)
            self.assertEqual(res, "https://copenhagenmarathon.dk/en/")

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_extract_with_llm_mode_override(self, mock_run, mock_which):
        # Mock both CLIs are available
        mock_which.side_effect = lambda cmd: f"/usr/local/bin/{cmd}" if cmd in ("agy", "opencode") else None

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "```json\n{\n  \"event_date\": \"2027-04-25\",\n  \"registration_windows\": [],\n  \"confidence\": \"high\",\n  \"notes\": \"Mocked CLI\",\n  \"raw_evidence\": []\n}\n```"
        mock_run.return_value = mock_result

        # Even with agy available, if LLM_MODE=opencode, it must use opencode
        with patch.dict(os.environ, {"LLM_MODE": "opencode"}, clear=True):
            res = extract_with_llm("London Marathon", "Some page text")
            self.assertIsNotNone(res)
            mock_run.assert_called_once()
            self.assertEqual(mock_run.call_args[0][0][0], "opencode")

        mock_run.reset_mock()

        # If LLM_MODE=agy, it must use agy
        with patch.dict(os.environ, {"LLM_MODE": "agy"}, clear=True):
            res = extract_with_llm("London Marathon", "Some page text")
            self.assertIsNotNone(res)
            mock_run.assert_called_once()
            self.assertEqual(mock_run.call_args[0][0][0], "agy")

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_resolve_official_url_modes(self, mock_run, mock_which):
        # Mock both CLIs are available
        mock_which.side_effect = lambda cmd: f"/usr/local/bin/{cmd}" if cmd in ("agy", "opencode") else None

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "https://www.londonmarathon.com"
        mock_run.return_value = mock_result

        # Case 1: LLM_MODE=opencode -> should call opencode
        with patch.dict(os.environ, {"LLM_MODE": "opencode"}, clear=True):
            res = resolve_official_url("London Marathon")
            self.assertEqual(res, "https://www.londonmarathon.com")
            mock_run.assert_called_once()
            self.assertEqual(mock_run.call_args[0][0][0], "opencode")

        mock_run.reset_mock()

        # Case 2: LLM_MODE=agy -> should call agy
        with patch.dict(os.environ, {"LLM_MODE": "agy"}, clear=True):
            res = resolve_official_url("London Marathon")
            self.assertEqual(res, "https://www.londonmarathon.com")
            mock_run.assert_called_once()
            self.assertEqual(mock_run.call_args[0][0][0], "agy")

        mock_run.reset_mock()

        # Case 3: LLM_MODE=api but no API key -> should not run and return None (since api mode doesn't fallback)
        with patch.dict(os.environ, {"LLM_MODE": "api"}, clear=True):
            res = resolve_official_url("London Marathon")
            self.assertIsNone(res)
            mock_run.assert_not_called()

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_resolve_event_webpage_modes(self, mock_run, mock_which):
        # Mock both CLIs are available
        mock_which.side_effect = lambda cmd: f"/usr/local/bin/{cmd}" if cmd in ("agy", "opencode") else None

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "https://www.londonmarathon.com/register"
        mock_run.return_value = mock_result

        # Case 1: LLM_MODE=opencode -> should call opencode
        with patch.dict(os.environ, {"LLM_MODE": "opencode"}, clear=True):
            res = resolve_event_webpage("London Marathon", 2027)
            self.assertEqual(res, "https://www.londonmarathon.com/register")
            mock_run.assert_called_once()
            self.assertEqual(mock_run.call_args[0][0][0], "opencode")

        mock_run.reset_mock()

        # Case 2: LLM_MODE=agy -> should call agy
        with patch.dict(os.environ, {"LLM_MODE": "agy"}, clear=True):
            res = resolve_event_webpage("London Marathon", 2027)
            self.assertEqual(res, "https://www.londonmarathon.com/register")
            mock_run.assert_called_once()
            self.assertEqual(mock_run.call_args[0][0][0], "agy")

        mock_run.reset_mock()

        # Case 3: LLM_MODE=api but no API key -> should not run and return None
        with patch.dict(os.environ, {"LLM_MODE": "api"}, clear=True):
            res = resolve_event_webpage("London Marathon", 2027)
            self.assertIsNone(res)
            mock_run.assert_not_called()

if __name__ == "__main__":
    unittest.main()
