import unittest
from unittest.mock import patch, MagicMock
import urllib.error

from marathon_tracker.fetch import check_url, fetch_text, html_to_text

class TestFetch(unittest.TestCase):
    def test_html_to_text_cleans_script_and_style(self):
        html = "<html><body><h1>Hello World</h1><style>body { color: red; }</style><script>alert('1');</script></body></html>"
        text = html_to_text(html)
        self.assertIn("Hello World", text)
        self.assertNotIn("alert", text)
        self.assertNotIn("body {", text)

    @patch("urllib.request.urlopen")
    def test_check_url_reachable(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_response

        reachable, error = check_url("https://example.com")
        self.assertTrue(reachable)
        self.assertIsNone(error)

    @patch("urllib.request.urlopen")
    def test_check_url_unreachable(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "https://example.com", 404, "Not Found", {}, None
        )
        reachable, error = check_url("https://example.com")
        self.assertFalse(reachable)
        self.assertEqual(error, "HTTP 404")

    @patch("urllib.request.urlopen")
    def test_fetch_text_success(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = b"<html><body>hello</body></html>"
        
        # Mock response headers get_content_charset method
        mock_headers = MagicMock()
        mock_headers.get_content_charset.return_value = "utf-8"
        mock_response.headers = mock_headers
        
        mock_urlopen.return_value.__enter__.return_value = mock_response

        text = fetch_text("https://example.com")
        self.assertEqual(text.strip(), "hello")

if __name__ == "__main__":
    unittest.main()
