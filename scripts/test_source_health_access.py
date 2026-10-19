#!/usr/bin/env python3
"""Source-health denial and transient-status fixtures; no network requests."""
import unittest
from unittest.mock import patch

import check_source_health as health


class SourceAccessTests(unittest.TestCase):
    def probe(self, status, body=b"", kind="html"):
        with patch.object(health, "_get", return_value=(status, body, "")) as get, \
                patch.object(health.time, "sleep") as sleep:
            result = health.probe("https://fixture.invalid/source", kind)
        get.assert_called_once_with("https://fixture.invalid/source", health.UA)
        sleep.assert_not_called()
        return result

    def test_auth_quota_and_security_denials_never_retry_with_other_identity(self):
        for status in (401, 403, 406, 407, 409, 429, 451):
            with self.subTest(status=status):
                result = self.probe(status)
                self.assertEqual(result["status"], status)
                self.assertEqual(result["판정"], "BLOCKED")
                self.assertFalse(result["ok"])
                self.assertEqual(result["items"], 0)
                self.assertTrue(result["blocked_for_bot"])
                self.assertEqual(result["ua"], "bot")

    def test_security_interstitial_200_is_not_healthy_html(self):
        for title in ("Access Denied", "Forbidden", "Unauthorized", "CAPTCHA", "Security Check", "Just a moment..."):
            with self.subTest(title=title):
                body = (f"<html><title>{title}</title>" + "x" * 2500 + "</html>").encode()
                result = self.probe(200, body)
                self.assertFalse(result["ok"])
                self.assertEqual(result["판정"], "BLOCKED")
                self.assertEqual(result["bytes"], len(body))

    def test_not_found_does_not_switch_identity(self):
        result = self.probe(404)
        self.assertEqual(result["판정"], "GONE")
        self.assertFalse(result["ok"])

    def test_security_news_titles_are_not_access_denials(self):
        body = b"<rss><channel><title>Security Check News</title><item><title>Unauthorized access incident investigated</title></item></channel></rss>"
        result = self.probe(200, body, "rss")
        self.assertTrue(result["ok"])
        self.assertEqual(result["items"], 1)
        self.assertEqual(result["판정"], "LIVE")
        html = ("<html><head><title>Unauthorized access incident investigated</title></head><body>" + "x" * 2500 + "</body></html>").encode()
        self.assertEqual(self.probe(200, html)["판정"], "LIVE")

    def test_html_security_gate_at_feed_url_is_still_blocked(self):
        body = b"<!DOCTYPE html><html><head><title>Access Denied</title></head><body>Restricted</body></html>"
        self.assertEqual(self.probe(200, body, "rss")["판정"], "BLOCKED")

    def test_transient_status_stays_down_without_auth_stop_or_invented_success(self):
        for status in (0, 500, 502, 503, 504):
            with self.subTest(status=status):
                result = self.probe(status)
                self.assertEqual(result["판정"], "DOWN")
                self.assertFalse(result["blocked_for_bot"])
                self.assertFalse(result["ok"])

    def test_valid_feed_and_empty_response_keep_existing_meaning(self):
        result = self.probe(200, b"<rss><channel><item><title>Fixture</title></item></channel></rss>", "rss")
        self.assertTrue(result["ok"])
        self.assertEqual(result["items"], 1)
        self.assertEqual(result["판정"], "LIVE")
        result = self.probe(200, b"<rss><channel/></rss>", "rss")
        self.assertFalse(result["ok"])
        self.assertEqual(result["판정"], "EMPTY")


if __name__ == "__main__":
    unittest.main(verbosity=2)
