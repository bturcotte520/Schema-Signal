import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from schema_signal.cli import main
from schema_signal.core import Reply


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "run"
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stdout(self.stdout))
        self.stack.enter_context(contextlib.redirect_stderr(self.stderr))

    def report(self):
        return json.loads((self.output / "report.json").read_text())

    def test_default_is_dry_run_no_network(self):
        with patch("schema_signal.core.Client.send", side_effect=AssertionError("network forbidden")):
            self.assertEqual(main(["--out", str(self.output)]), 0)
        self.assertIn("DRY RUN", self.report()["mode"])
        self.assertEqual([r["status"] for r in self.report()["results"]], ["not_run", "not_run"])
        self.assertEqual(len(list(self.output.iterdir())), 5)

    def test_demo_no_key_no_network(self):
        with patch.dict(os.environ, {}, clear=True), patch("schema_signal.core.Client.send", side_effect=AssertionError("network forbidden")):
            self.assertEqual(main(["--demo", "--out", str(self.output)]), 0)
        self.assertIn("SIMULATED", self.report()["mode"])
        self.assertEqual([r["status"] for r in self.report()["results"]], ["schema_mismatch", "valid"])

    def test_live_requires_key(self):
        with patch.dict(os.environ, {}, clear=True), patch("schema_signal.core.Client.send") as send:
            self.assertEqual(main(["--live", "--out", str(self.output)]), 2)
            send.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_existing_directory_never_overwritten(self):
        self.output.mkdir()
        marker = self.output / "marker"
        marker.write_text("keep")
        self.assertEqual(main(["--out", str(self.output)]), 2)
        self.assertEqual(marker.read_text(), "keep")

    def test_live_two_posts_and_secret_absent(self):
        key = "fake-test-only-key"
        body = json.dumps({"provider": key, "id": "gen-secret", "choices": [{"finish_reason": "stop", "message": {"content": '{"item":"notebook","quantity":3}'}}]}).encode()
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": key}), patch("schema_signal.core.Client.send", return_value=Reply(200, body)) as send:
            self.assertEqual(main(["--live", "--out", str(self.output)]), 0)
            self.assertEqual(send.call_count, 2)
            self.assertEqual([call.args[1]["provider"]["require_parameters"] for call in send.call_args_list], [False, True])
        for path in self.output.iterdir():
            self.assertNotIn(key, path.read_text())
            self.assertNotIn("gen-secret", path.read_text())
        self.assertNotIn(key, self.stdout.getvalue())

    def test_auth_or_rate_limit_stops_second_generation(self):
        for status in (401, 402, 403, 429):
            with self.subTest(status=status):
                target = self.output / str(status)
                with patch.dict(os.environ, {"OPENROUTER_API_KEY": "fake-test-key"}), patch("schema_signal.core.Client.send", return_value=Reply(status, b"{}")) as send:
                    self.assertEqual(main(["--live", "--out", str(target)]), 1)
                    self.assertEqual(send.call_count, 1)
                report = json.loads((target / "report.json").read_text())
                self.assertEqual(report["results"][1]["status"], "skipped_after_auth_credits_or_rate_limit")

    def test_model_argument_rejects_shell_injection(self):
        with self.assertRaises(SystemExit):
            main(["--model", "x; cat /tmp/no", "--out", str(self.output)])

    def test_repro_uses_env_key_not_embedded_key(self):
        main(["--demo", "--out", str(self.output)])
        script = (self.output / "reproduce.sh").read_text()
        self.assertIn("${OPENROUTER_API_KEY}", script)
        self.assertNotIn("--retry", script)
        self.assertNotIn("--location", script)

    def custom_args(self, schema='{"type":"integer","minimum":2}', prompt="Return a synthetic integer"):
        prompt_path = Path(self.temp.name) / "prompt.txt"
        schema_path = Path(self.temp.name) / "schema.json"
        prompt_path.write_text(prompt, encoding="utf-8")
        schema_path.write_text(schema, encoding="utf-8")
        return ["--prompt-file", str(prompt_path), "--schema-file", str(schema_path),
                "--acknowledge-private-inputs", "--out", str(self.output)]

    def test_custom_live_validation_and_privacy(self):
        key = "fake-custom-test-key"
        args = self.custom_args('{"type":"integer","description":"PRIVATE_SCHEMA"}',
                                f"PRIVATE_CUSTOMER {key} sk-or-fake-token Bearer fake-bearer")
        body = json.dumps({"provider": "Test provider", "choices": [{"message": {"content": '3'}}]}).encode()
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": key}), patch("schema_signal.core.Client.send", return_value=Reply(200, body, 42)) as send:
            self.assertEqual(main(["--live", *args]), 0)
            self.assertEqual(send.call_count, 2)
            self.assertIn("PRIVATE_CUSTOMER", send.call_args.args[1]["messages"][0]["content"])
        report = self.report()
        self.assertTrue(report["review_required_before_sharing"])
        self.assertEqual([r["status"] for r in report["results"]], ["valid", "valid"])
        for path in self.output.iterdir():
            text = path.read_text()
            for secret in (key, "sk-or-fake-token", "fake-bearer"):
                self.assertNotIn(secret, text)
            if path.name.startswith("report"):
                self.assertNotIn("PRIVATE_CUSTOMER", text)
                self.assertNotIn("PRIVATE_SCHEMA", text)
        request_text = (self.output / "request-off.json").read_text()
        self.assertIn("PRIVATE_CUSTOMER", request_text)
        self.assertIn("PRIVATE_SCHEMA", request_text)
        self.assertIn("scrubbing is not anonymization", self.stdout.getvalue())

    def test_custom_requires_privacy_acknowledgment(self):
        args = self.custom_args()
        args.remove("--acknowledge-private-inputs")
        self.assertEqual(main(args), 2)
        self.assertFalse(self.output.exists())

    def test_custom_files_must_be_paired(self):
        self.assertEqual(main(["--prompt-file", "missing", "--out", str(self.output)]), 2)
        self.assertIn("both", self.stderr.getvalue())

    def test_custom_demo_rejected(self):
        self.assertEqual(main(["--demo", *self.custom_args()]), 2)
        self.assertFalse(self.output.exists())

    def test_invalid_custom_inputs_rejected_before_network_or_output(self):
        schemas = ['{', '{"type":"PRIVATE_INVALID_TYPE"}', '[]',
                   '{"type":"integer","minimum":NaN}', '{"type":"integer","minimum":1e999}',
                   '{"type":"integer","type":"string"}',
                   '{"$ref":"https://example.invalid/private"}',
                   '{"$defs":{"x":{"$dynamicRef":"#x"}}}',
                   '{"$schema":"http://json-schema.org/draft-07/schema#"}',
                   '{"pattern":"["}']
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "fake-test-key"}), patch("schema_signal.core.Client.send") as send:
            for schema in schemas:
                with self.subTest(schema=schema):
                    self.assertEqual(main(["--live", *self.custom_args(schema)]), 2)
                    self.assertFalse(self.output.exists())
            send.assert_not_called()
        self.assertNotIn("PRIVATE_INVALID_TYPE", self.stderr.getvalue())

    def test_empty_oversized_missing_and_non_utf8_inputs(self):
        for prompt in ("  \n", "x" * 65537):
            self.assertEqual(main(self.custom_args(prompt=prompt)), 2)
        args = self.custom_args()
        Path(args[1]).write_bytes(b"\xff")
        self.assertEqual(main(args), 2)
        Path(args[1]).unlink()
        self.assertEqual(main(args), 2)
        self.assertFalse(self.output.exists())

    def test_offline_exports_scrub_environment_key_too(self):
        key = "offline-fake-key"
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": key}):
            self.assertEqual(main(self.custom_args(prompt=key)), 0)
        for path in self.output.iterdir():
            self.assertNotIn(key, path.read_text())


if __name__ == "__main__":
    unittest.main()
