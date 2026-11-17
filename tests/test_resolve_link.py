import unittest
import asyncio
from unittest.mock import patch, MagicMock
from resolve_link import (
    sanitize_s3_url,
    extract_links_from_text,
    extract_final_link,
    extract_final_link_async,
    normalize_paste_url,
)

class TestResolveLink(unittest.TestCase):
    def test_normalize_paste_url(self):
        self.assertEqual(normalize_paste_url("https://pastebin.com/abcd123"), "https://pastebin.com/raw/abcd123")
        self.assertEqual(normalize_paste_url("https://rentry.co/mytext"), "https://rentry.co/mytext/raw")
        self.assertEqual(normalize_paste_url("https://paste.ee/p/xyz"), "https://paste.ee/r/xyz")
        self.assertEqual(normalize_paste_url("https://dpaste.org/sample"), "https://dpaste.org/sample/raw")

    def test_pastelink_filter_internal_and_ads(self):
        html_pastelink = '''
        <html>
        <link rel="stylesheet" href="/assets/css/styles.css">
        <a href="https://fonts.gstatic.com">Font</a>
        <button data-url="https://pslk.net/8k0t0va3">Shortlink</button>
        <p><a href="https://t.me/PastelinkVIPChannel">Join VIP</a></p>
        <a href="https://www.facebook.com/sharer">Share</a>
        <a href="https://go.nordvpn.net/aff_c">Ad</a>
        </html>
        '''
        links = extract_links_from_text(html_pastelink, source_url="https://pastelink.net/8k0t0va3")
        self.assertEqual(links, ["https://t.me/PastelinkVIPChannel"])

    def test_sanitize_s3_url(self):
        raw = "https://s3.amazonaws.com/bucket/file.txt?AWSAccessKeyId=AKIAIOSFODNN7EXAMPLE&amp;Signature=vjbyPxybdZaNmGa%2ByT272YEAiv4%3D&amp;Expires=1700000000"
        cleaned = sanitize_s3_url(raw)
        self.assertNotIn("&amp;", cleaned)
        self.assertIn("&Signature=", cleaned)
        self.assertIn("&Expires=", cleaned)

    def test_sanitize_quotes_and_spaces(self):
        raw = '  "https://example.com/test?a=1&amp;b=2"  '
        cleaned = sanitize_s3_url(raw)
        self.assertEqual(cleaned, "https://example.com/test?a=1&b=2")

    def test_extract_telegram_html(self):
        html_content = '<p><a href="https://t.me/+join12345">https://t.me/+join12345</a></p>'
        links = extract_links_from_text(html_content)
        self.assertEqual(links, ["https://t.me/+join12345"])

    def test_extract_telegram_priority(self):
        mixed = "Check this: https://google.com and telegram: https://t.me/mychannel?start=ref123"
        links = extract_links_from_text(mixed)
        self.assertEqual(links[0], "https://t.me/mychannel?start=ref123")

    def test_trailing_punctuation_strip(self):
        text = "Join us at https://t.me/cryptogroup."
        links = extract_links_from_text(text)
        self.assertEqual(links[0], "https://t.me/cryptogroup")

    def test_mock_fetch_success(self):
        fake_html = '<p><a href="https://t.me/SuperSecretChannel">Click</a></p>'.encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_html
        mock_resp.headers.get_content_charset.return_value = "utf-8"
        mock_resp.geturl.return_value = "https://s3.amazonaws.com/bucket/link.txt"
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            link = extract_final_link("https://s3.amazonaws.com/bucket/link.txt?Signature=abc&amp;Key=123")
            self.assertEqual(link, "https://t.me/SuperSecretChannel")

    def test_mock_fetch_async(self):
        fake_html = '<p><a href="https://t.me/AsyncChannel">Click</a></p>'.encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_html
        mock_resp.headers.get_content_charset.return_value = "utf-8"
        mock_resp.geturl.return_value = "https://s3.amazonaws.com/bucket/link.txt"
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            async def run_async():
                return await extract_final_link_async("https://s3.amazonaws.com/bucket/link.txt")
            link = asyncio.run(run_async())
            self.assertEqual(link, "https://t.me/AsyncChannel")

if __name__ == "__main__":
    unittest.main()
