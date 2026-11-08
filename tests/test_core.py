import io
import json
import unittest
import urllib.error
from unittest.mock import Mock

from schema_signal.core import (
    API, Client, MAX_RESPONSE_BYTES, NoRedirect, Reply, analyze, make_request,
    probe, scrub,
)


def response(content='{"item":"blue notebooks","quantity":3}', **extra):
    body = {"model": "example/model", "provider": "Example provider",
            "choices": [{"finish_reason": "stop", "message": {"content": content}}]}
    body.update(extra)
    return Reply(200, json.dumps(body).encode())


class AnalyzeTests(unittest.TestCase):
    def test_requests_differ_only_in_flag(self):
        off = make_request("example/model", False, "provider-slug")
        on = make_request("example/model", True, "provider-slug")
        on["provider"]["require_parameters"] = False
        self.assertEqual(off, on)
        self.assertFalse(on["provider"]["allow_fallbacks"])
        self.assertEqual(on["provider"]["only"], ["provider-slug"])

    def test_requests_do_not_share_mutable_schema(self):
        one = make_request("example/model", False)
        one["response_format"]["json_schema"]["schema"]["required"].clear()
        self.assertEqual(len(make_request("example/model", True)["response_format"]["json_schema"]["schema"]["required"]), 2)

    def test_valid(self):
        result, _ = analyze(response())
        self.assertEqual(result["status"], "valid")
        self.assertTrue(result["validation"]["schema_valid"])
        self.assertEqual(result["routing"]["source"], "chat_response.provider")

    def test_schema_wrong_type(self):
        result, _ = analyze(response('{"item":"SECRET_TEXT","quantity":"3"}'))
        self.assertEqual(result["status"], "schema_mismatch")
        self.assertEqual(result["validation"]["failed_keywords"], ["type"])
        self.assertNotIn("SECRET_TEXT", json.dumps(result))

    def test_additional_and_missing_fields(self):
        result, _ = analyze(response('{"quantity":3,"extra":true}'))
        self.assertEqual(result["validation"]["failed_keywords"], ["additionalProperties", "required"])

    def test_boolean_is_not_integer(self):
        result, _ = analyze(response('{"item":"notebook","quantity":true}'))
        self.assertEqual(result["status"], "schema_mismatch")

    def test_invalid_json_not_repaired(self):
        for content in ('```json\n{}\n```', '{"item":"a","quantity":NaN}', '{"item":"a","quantity":1,"quantity":2}'):
            with self.subTest(content=content):
                result, _ = analyze(response(content))
                self.assertEqual(result["status"], "invalid_json")

    def test_refusal(self):
        result, _ = analyze(response(choices=[{"message": {"refusal": "SECRET", "content": None}}]))
        self.assertEqual(result["status"], "refusal")
        self.assertNotIn("SECRET", json.dumps(result))

    def test_content_filter(self):
        result, _ = analyze(response(choices=[{"finish_reason": "content_filter", "message": {}}]))
        self.assertEqual(result["status"], "refusal")

    def test_truncation_even_if_json_valid(self):
        result, _ = analyze(response(choices=[{"finish_reason": "length", "message": {"content": '{"item":"a","quantity":3}'}}]))
        self.assertEqual(result["status"], "truncated")
        self.assertTrue(result["validation"]["schema_valid"])

    def test_malformed_response_shapes(self):
        for body in ([], {}, {"choices": []}, {"choices": [None]}, {"choices": [{"message": []}]}):
            with self.subTest(body=body):
                result, _ = analyze(Reply(200, json.dumps(body).encode()))
                self.assertEqual(result["status"], "malformed_response")

    def test_missing_content(self):
        result, _ = analyze(response(None))
        self.assertEqual(result["status"], "missing_content")

    def test_api_errors_never_export_raw(self):
        for status in (200, 400, 401, 402, 404, 429, 502):
            with self.subTest(status=status):
                result, _ = analyze(Reply(status, json.dumps({"error": {"code": 123, "message": "SECRET", "metadata": {"raw": "SECRET"}}}).encode()))
                self.assertIn(result["status"], ("upstream_error", "http_error"))
                self.assertEqual(result["api_error_code"], 123)
                self.assertNotIn("SECRET", json.dumps(result))

    def test_http_error_non_json(self):
        self.assertEqual(analyze(Reply(502, b"<html>SECRET</html>"))[0]["status"], "http_error")

    def test_bad_json_success(self):
        self.assertEqual(analyze(Reply(200, b"not json"))[0]["status"], "invalid_api_json")

    def test_transport_failure(self):
        result, _ = analyze(Reply(None, transport_error="network_or_timeout"))
        self.assertEqual(result["status"], "network_or_timeout")
        self.assertIsNone(result["validation"]["schema_valid"])

    def test_generation_id_is_not_in_result(self):
        result, generation_id = analyze(response(id="gen-abc123"))
        self.assertEqual(generation_id, "gen-abc123")
        self.assertNotIn("gen-abc123", json.dumps(result))

    def test_malformed_id_not_used(self):
        for value in ("../secret", "gen-abc&extra=yes", "https://evil.invalid", "gen-" + "a" * 125):
            self.assertIsNone(analyze(response(id=value))[1])

    def test_usage_is_allowlisted(self):
        result, _ = analyze(response(usage={"prompt_tokens": 12, "cost": 0.001, "secret": "SECRET", "completion_tokens": "SECRET"}))
        self.assertEqual(result["usage"], {"prompt_tokens": 12, "cost": 0.001})

    def test_scrub_recurses(self):
        value = {"outer": [{"a": "this is the-actual-key", "b": "Bearer another-secret", "c": "sk-or-v1-hidden"}]}
        encoded = json.dumps(scrub(value, "the-actual-key"))
        for secret in ("the-actual-key", "another-secret", "sk-or-v1-hidden"):
            self.assertNotIn(secret, encoded)


class ProbeTests(unittest.TestCase):
    def test_provider_returned_no_lookup(self):
        client = Mock()
        client.send.return_value = response(id="gen-abc")
        result = probe(client, make_request("example/model", True))
        self.assertEqual(client.send.call_count, 1)
        self.assertEqual(result["metadata_lookup"], "not_needed")

    def test_generation_metadata_fallback(self):
        client = Mock()
        client.send.side_effect = [response(provider=None, id="gen-abc"), Reply(200, b'{"data":{"provider_name":"Metadata provider","secret":"NO"}}')]
        result = probe(client, make_request("example/model", True))
        self.assertEqual(result["routing"]["provider"], "Metadata provider")
        self.assertEqual(result["routing"]["source"], "generation.data.provider_name")
        self.assertEqual(client.send.call_args.args[0], "/generation?id=gen-abc")
        self.assertNotIn("NO", json.dumps(result))

    def test_unavailable_metadata_keeps_unknown(self):
        for metadata in (Reply(404, b"{}"), Reply(None, transport_error="network_or_timeout"), Reply(200, b"[]")):
            client = Mock()
            client.send.side_effect = [response(provider=None, id="gen-abc"), metadata]
            result = probe(client, make_request("example/model", True))
            self.assertEqual(result["metadata_lookup"], "unavailable")
            self.assertIsNone(result["routing"]["provider"])
            self.assertEqual(result["status"], "valid")


class FakeHTTP(io.BytesIO):
    def __init__(self, body, code=200):
        super().__init__(body)
        self.code = code


class HTTPTests(unittest.TestCase):
    def test_request_headers_url_timeout_and_no_retries(self):
        client = Client("test-secret", 7)
        client.opener = Mock()
        client.opener.open.return_value = FakeHTTP(b"{}")
        reply = client.send("/chat/completions", make_request("example/model", False))
        request = client.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, API + "/chat/completions")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-secret")
        self.assertEqual(client.opener.open.call_args.kwargs["timeout"], 7)
        self.assertEqual(client.opener.open.call_count, 1)
        self.assertEqual(reply.status, 200)

    def test_http_error_is_read(self):
        client = Client("test-secret")
        client.opener = Mock()
        client.opener.open.side_effect = urllib.error.HTTPError(API, 429, "Too many", {}, io.BytesIO(b'{"error":{"code":429}}'))
        reply = client.send("/chat/completions", {})
        self.assertEqual(reply.status, 429)
        self.assertEqual(client.opener.open.call_count, 1)

    def test_timeout_no_retry(self):
        client = Client("test-secret")
        client.opener = Mock()
        client.opener.open.side_effect = TimeoutError("SECRET")
        reply = client.send("/chat/completions", {})
        self.assertEqual(reply.transport_error, "network_or_timeout")
        self.assertEqual(client.opener.open.call_count, 1)
        self.assertNotIn("SECRET", str(reply))

    def test_response_size_limit(self):
        client = Client("test-secret")
        client.opener = Mock()
        client.opener.open.return_value = FakeHTTP(b"a" * (MAX_RESPONSE_BYTES + 1))
        self.assertEqual(client.send("/chat/completions", {}).transport_error, "response_too_large")

    def test_redirects_disabled(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.invalid"))

    def test_arbitrary_urls_disallowed(self):
        with self.assertRaises(ValueError):
            Client("test-secret").send("https://evil.invalid")


if __name__ == "__main__":
    unittest.main()
