"""Tests for the interactive command-line chat (bankassist.cli), run as a subprocess.

The CLI is started with cwd=src and a temporary HOME, and its stdin is piped.
REPO_ROOT inside the CLI is pointed at a temporary folder, so the session trace
it saves on exit never lands in the repository.  As a safety net, tearDown
also removes any new file that shows up in <repo>/traces/interactive.

getpass() normally reads from the controlling terminal; the subprocess is
started in a new session (no controlling terminal), so getpass falls back to
reading the piped stdin.  That trick is POSIX-only, hence the skip on Windows.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from . import _path, _helpers as H
except ImportError:
    import _path
    import _helpers as H

# Runs bankassist.cli.main() with REPO_ROOT redirected to argv[1]; the rest of argv goes to the CLI.
_RUNNER = ("import sys; from pathlib import Path; import bankassist.cli as cli; "
           "cli.REPO_ROOT = Path(sys.argv[1]); cli.main(sys.argv[2:])")
REPO_INTERACTIVE = Path(_path.REPO_ROOT, "traces", "interactive")


def _listing(folder: Path) -> set[Path]:
    return set(folder.glob("*")) if folder.is_dir() else set()


@unittest.skipUnless(os.name == "posix", "getpass fallback to piped stdin needs a POSIX session")
class CLITest(unittest.TestCase):

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(prefix="bankassist-cli-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.repo_before = _listing(REPO_INTERACTIVE)
        self.repo_dir_existed = REPO_INTERACTIVE.is_dir()

    def tearDown(self):
        # nothing should have been written into the repo, but clean up if it was
        for p in _listing(REPO_INTERACTIVE) - self.repo_before:
            p.unlink()
        if not self.repo_dir_existed and REPO_INTERACTIVE.is_dir() and not any(REPO_INTERACTIVE.iterdir()):
            REPO_INTERACTIVE.rmdir()
        super().tearDown()

    def run_cli(self, args: list[str], lines: list[str]) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k not in _path.LLM_ENV_VARS}
        env.update(HOME=str(self.tmp), PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        proc = subprocess.run(
            [sys.executable, "-c", _RUNNER, str(self.tmp), *args],
            input="".join(line + "\n" for line in lines), capture_output=True, text=True,
            encoding="utf-8", cwd=_path.SRC_DIR, env=env, timeout=60, start_new_session=True)
        self.assertNotIn("Traceback", proc.stderr, proc.stderr)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc

    def saved_traces(self) -> list[dict]:
        files = sorted((self.tmp / "traces" / "interactive").glob("session-*.json"))
        return [json.loads(p.read_text(encoding="utf-8")) for p in files]

    # ------------------------------------------------------------------ tests
    def test_failed_login_asks_for_pin_again(self):  # P1, P3
        proc = self.run_cli(["--customer", "c001", "--pin", "9999"],
                            ["balance", "1234", "What is my balance?", "quit"])
        out = proc.stdout
        self.assertIn("$2,450.00", out)
        self.assertEqual(out.count("2 attempt(s) left"), 1, out)
        self.assertNotIn("1 attempt(s) left", out)
        # never reached the lockout message ("...profile is locked after too many failed PIN attempts")
        self.assertNotIn("locked after too many", out)
        self.assertIn("Not logged in. Enter the PIN again", out)
        self.assertIn("C001>", out)  # the typed "c001" was upper-cased

        [trace] = self.saved_traces()
        auths = [e for e in trace["events"] if e["kind"] == "message"
                 and e["to"] == "AuthAgent" and e["performative"] == "authenticate"]
        self.assertEqual(len(auths), 2)  # one wrong PIN, one correct: the wrong one was not resent
        self.assertEqual(H.find_pin_leaks(trace, {"1234", "9999"}), [])  # P2
        # the PIN line typed at the prompt was never treated as a chat message
        self.assertEqual([e["content"] for e in trace["events"] if e["kind"] == "user_input"],
                         ["balance", "What is my balance?"])

    def test_logout_at_pin_prompt_switches_customer(self):
        proc = self.run_cli(["--customer", "c001", "--pin", "0000"],
                            ["balance", "logout", "c002", "5678", "what's my balance?", "quit"])
        self.assertIn("$830.50", proc.stdout)
        self.assertIn("C002>", proc.stdout)
        self.assertEqual(proc.stdout.count("attempt(s) left"), 1)

    def test_eof_at_customer_prompt_exits_cleanly(self):
        proc = self.run_cli([], [])
        self.assertIn("Customer ID:", proc.stdout)
        self.assertIn("Trace saved to", proc.stdout)

    def test_eof_while_chatting_exits_cleanly(self):
        proc = self.run_cli(["--customer", "C001", "--pin", "1234"], ["What's my balance?"])
        self.assertIn("$2,450.00", proc.stdout)

    def test_trace_saved_outside_the_repo(self):
        self.run_cli(["--customer", "C001", "--pin", "1234"], ["help", "quit"])
        self.assertEqual(len(self.saved_traces()), 1)
        self.assertEqual(_listing(REPO_INTERACTIVE), self.repo_before)


if __name__ == "__main__":
    unittest.main()
