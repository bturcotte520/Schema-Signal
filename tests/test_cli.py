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


if __name__ == "__main__":
    unittest.main()
