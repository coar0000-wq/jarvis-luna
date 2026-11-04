#!/usr/bin/env python3
from __future__ import annotations

import unittest
from unittest.mock import patch

import gemini_escalation as ge


class GeminiEscalationTest(unittest.TestCase):
    def docs(self, parse_other: bool = False, repeated: bool = False):
        return {
            "ops_plan.json": {"risk": "low", "tasks": []},
            "collector_audit.json": {
                "failure_types": ([{"type": "parse_other", "pd_no": "x"}]
                                  if parse_other else [])
            },
            "signal_audit.json": {"empty_or_failed": []},
            "remediation_state.json": {
                "issues": {
                    "human": {
                        "classification": "human_approval_required",
                        "detected_runs": 5,
                        "resolved_at": None,
                    },
                    **({
                        "auto": {
                            "classification": "revalidate_only",
                            "detected_runs": 3,
                            "resolved_at": None,
                            "key": "auto",
                        }
                    } if repeated else {}),
                }
            },
            "typesafe_advisory.json": {"items": {}},
        }

    def reasons(self, docs):
        def fake_load(path, default):
            return docs.get(path.name, default)
        with patch.object(ge, "load", side_effect=fake_load):
            return ge.insufficiency_reasons()[0]

    def test_human_only_does_not_call_gemini(self):
        self.assertEqual(self.reasons(self.docs()), [])

    def test_unclassified_parser_failure_escalates(self):
        self.assertIn("unclassified_parse_failures=1",
                      self.reasons(self.docs(parse_other=True)))

    def test_repeated_revalidation_escalates(self):
        self.assertIn("repeated_unresolved_auto_issues=1",
                      self.reasons(self.docs(repeated=True)))


class MistralFallbackTest(unittest.TestCase):
    """2026-11-04: Mistral Large 4 무료 모드는 같은 1회 호출 안에서만 Gemini를 대신한다."""
    STOPPED = {"provider": "gemini", "status": "provider_stopped", "error": "stop_http_429"}

    def choose(self, previous, gemini, mistral, free="1"):
        with patch.dict("os.environ", {"MISTRAL_FREE_MODE_ONLY": free}, clear=False):
            return ge.choose_provider(previous, gemini, mistral)

    def test_gemini_stays_primary(self):
        self.assertEqual(self.choose({}, "g", "m"), "gemini")
        self.assertEqual(self.choose({"status": "advisory_ready", "provider": "gemini"}, "g", "m"), "gemini")

    def test_mistral_after_gemini_stop_or_missing_key(self):
        self.assertEqual(self.choose(self.STOPPED, "g", "m"), "mistral")
        self.assertEqual(self.choose({}, "", "m"), "mistral")

    def test_mistral_requires_key_and_free_mode_flag(self):
        self.assertEqual(self.choose(self.STOPPED, "g", ""), "gemini")
        self.assertEqual(self.choose(self.STOPPED, "g", "m", free="0"), "gemini")
        self.assertIsNone(self.choose({}, "", "m", free="0"))
        self.assertIsNone(self.choose({}, "", ""))

    def test_mistral_stop_returns_to_gemini_next_run(self):
        prev = {"provider": "mistral", "status": "provider_stopped", "error": "stop_http_429"}
        self.assertEqual(self.choose(prev, "g", "m"), "gemini")

    def fake_response(self, payload):
        class Response:
            def __enter__(self_inner):
                return self_inner
            def __exit__(self_inner, *args):
                return False
            def read(self_inner):
                import json
                return json.dumps(payload).encode("utf-8")
        return Response()

    def test_call_mistral_uses_low_reasoning_and_reads_text_part(self):
        captured = {}
        payload = {"choices": [{"message": {"content": [
            {"type": "thinking", "thinking": [{"type": "text", "text": "..."}]},
            {"type": "text", "text": '{"risk": "low", "diagnosis": "테스트", "next_safe_checks": [], "requires_human": false}'}]}}],
            "usage": {"total_tokens": 10}}
        def fake_urlopen(request, timeout=None):
            import json
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["auth"] = request.get_header("Authorization")
            return self.fake_response(payload)
        with patch.object(ge.urllib.request, "urlopen", side_effect=fake_urlopen):
            advice, usage = ge.call_mistral("secret", ["r"], {"c": 1})
        self.assertEqual(advice["risk"], "low")
        self.assertEqual(usage, {"total_tokens": 10})
        self.assertEqual(captured["url"], ge.MISTRAL_URL)
        self.assertEqual(captured["body"]["model"], ge.MISTRAL_MODEL)
        self.assertEqual(captured["body"]["reasoning_effort"], "low")
        self.assertLessEqual(captured["body"]["max_tokens"], 700)
        self.assertEqual(captured["auth"], "Bearer secret")

    def test_call_mistral_stops_on_quota_and_rejects_thinking_only(self):
        import io
        import urllib.error
        def quota(request, timeout=None):
            raise urllib.error.HTTPError(ge.MISTRAL_URL, 429, "quota", {}, io.BytesIO(b""))
        with patch.object(ge.urllib.request, "urlopen", side_effect=quota):
            with self.assertRaisesRegex(RuntimeError, "stop_http_429"):
                ge.call_mistral("k", ["r"], {})
        thinking_only = {"choices": [{"message": {"content": [{"type": "thinking", "thinking": []}]}}]}
        with patch.object(ge.urllib.request, "urlopen", return_value=self.fake_response(thinking_only)):
            with self.assertRaisesRegex(RuntimeError, "invalid_json_response"):
                ge.call_mistral("k", ["r"], {})


if __name__ == "__main__":
    unittest.main()
