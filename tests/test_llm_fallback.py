"""Tests for the optional LLM-backed Concierge and its fallback to the rule parser.

A tiny OpenAI-compatible server (POST /v1/chat/completions) runs on
127.0.0.1 in a background thread, so no real model or network is needed.
The BANKASSIST_LLM_* environment variables are patched per test and
restored afterwards.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

try:
    from . import _path, _helpers as H
except ImportError:
    import _path
    import _helpers as H

from bankassist import llm
from bankassist.agents import CONCIERGE_SYSTEM_PROMPT

ALICE, ALICE_PIN = "C001", "1234"
MODEL = "test-model-7b"


def _intent(**fields) -> dict:
    base = {k: None for k in ("intent", "account_id", "account_type", "from_account",
                              "from_type", "to_account", "amount")}
    base["skip_review"] = False
    base.update(fields)
    return base


def _completion(content: str) -> tuple[int, bytes]:
    body = {"id": "cmpl-1", "object": "chat.completion", "model": MODEL,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": content}}]}
    return 200, json.dumps(body).encode()


class _FakeLLMHandler(BaseHTTPRequestHandler):
    server: "_FakeLLMServer"

    def do_POST(self):  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        self.server.requests.append({"path": self.path, "headers": dict(self.headers),
                                     "body": json.loads(raw or b"{}")})
        status, body = self.server.respond()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep test output clean
        pass


class _FakeLLMServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _FakeLLMHandler)
        self.requests: list[dict] = []
        self.respond = lambda: _completion(json.dumps(_intent(intent="help")))

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/v1"


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LLMTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = _FakeLLMServer()
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        super().setUp()
        self.server.requests.clear()
        self.use_llm(self.server.base_url)

    def use_llm(self, base_url: str, api_key: str = "") -> None:
        no_proxy = "127.0.0.1,localhost"
        env = {"BANKASSIST_LLM_BASE_URL": base_url, "BANKASSIST_LLM_MODEL": MODEL,
               "BANKASSIST_LLM_API_KEY": api_key,
               "no_proxy": no_proxy + "," + os.environ.get("no_proxy", ""),
               "NO_PROXY": no_proxy + "," + os.environ.get("NO_PROXY", "")}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def reply_with(self, content: str | None = None, *, status: int = 200, raw: bytes | None = None):
        if raw is not None:
            self.server.respond = lambda: (status, raw)
        else:
            self.server.respond = lambda: _completion(content)

    def parse_events(self, tracer):
        acts = H.actions(tracer, "parse_request", agent="ConciergeAgent")
        obs = [e for e in H.events(tracer, "observation", "ConciergeAgent") if e["tool"] == "parse_request"]
        return acts, obs

    def fallback_thoughts(self, tracer):
        return [e for e in H.events(tracer, "thought", "ConciergeAgent")
                if "falling back to rule parser" in e["content"]]


# ===================================================================== LLM is used
class LLMConciergeTest(LLMTestBase):
    def test_config_read_from_env(self):
        cfg = llm.llm_config()
        self.assertEqual(cfg["base_url"], self.server.base_url)
        self.assertEqual(cfg["model"], MODEL)

    def test_concierge_uses_llm_output(self):
        # The rule parser cannot understand this text; only the LLM answer can.
        self.reply_with(json.dumps(_intent(intent="check_balance", account_type="savings")))
        app = H.new_app()
        self.assertTrue(app.tracer.meta["concierge_mode"].startswith("llm"))
        self.assertIn(MODEL, app.tracer.meta["concierge_mode"])

        text = "gimme the dough figure in the piggy bank"
        reply = app.chat(ALICE, ALICE_PIN, text)
        self.assertEqual(reply, "The balance of savings account ACC-1002 is $10,000.00.")

        acts, obs = self.parse_events(app.tracer)
        self.assertEqual(acts[0]["args"], {"text": text, "mode": "llm"})
        self.assertEqual(obs[0]["result"]["intent"], "check_balance")
        self.assertEqual(self.fallback_thoughts(app.tracer), [])

        # request format: OpenAI-compatible chat completion
        [req] = self.server.requests
        self.assertEqual(req["path"], "/v1/chat/completions")
        self.assertEqual(req["body"]["model"], MODEL)
        self.assertEqual(req["body"]["temperature"], 0)
        self.assertEqual(req["body"]["messages"],
                         [{"role": "system", "content": CONCIERGE_SYSTEM_PROMPT},
                          {"role": "user", "content": text}])
        self.assertNotIn("Authorization", req["headers"])

    def test_pin_is_never_sent_to_the_llm(self):  # P2
        self.reply_with(json.dumps(_intent(intent="check_balance")))
        H.new_app().chat(ALICE, ALICE_PIN, "What's my balance?")
        for req in self.server.requests:
            self.assertNotIn(ALICE_PIN, json.dumps(req["body"]))

    def test_api_key_sent_as_bearer_token(self):
        self.use_llm(self.server.base_url, api_key="secret-key")
        H.new_app().chat(ALICE, ALICE_PIN, "help")
        self.assertEqual(self.server.requests[-1]["headers"].get("Authorization"), "Bearer secret-key")

    def test_json_wrapped_in_prose_is_accepted(self):
        payload = json.dumps(_intent(intent="view_transactions", account_id="ACC-1001"))
        self.reply_with(f"Sure! Here is the JSON:\n```json\n{payload}\n```")
        app = H.new_app()
        reply = app.chat(ALICE, ALICE_PIN, "what happened on my main account lately")
        self.assertTrue(reply.startswith("Recent transactions on ACC-1001"), reply)
        self.assertEqual(self.fallback_thoughts(app.tracer), [])

    def test_extra_llm_fields_are_dropped(self):
        self.reply_with(json.dumps(_intent(intent="help", session_token="sess_x", pin="1234")))
        app = H.new_app()
        app.chat(ALICE, ALICE_PIN, "help")
        _, obs = self.parse_events(app.tracer)
        self.assertNotIn("session_token", obs[0]["result"])
        self.assertNotIn("pin", obs[0]["result"])

    def test_llm_transfer_still_reviewed_by_risk_agent(self):  # P8, P9
        self.reply_with(json.dumps(_intent(intent="transfer", to_account="ACC-2001",
                                           from_type="savings", amount=1500)))
        app = H.new_app()
        reply = app.chat(ALICE, ALICE_PIN, "shift fifteen hundred from the rainy-day fund to Bob")
        self.assertIn("Please confirm", reply)
        self.assertEqual(len(H.messages(app.tracer, to="RiskAgent", performative="assess_transfer")), 1)
        self.reply_with(json.dumps(_intent(intent="confirm")))
        self.assertTrue(app.chat(ALICE, ALICE_PIN, "sounds good").startswith("Done."))
        self.assertEqual(app.bank.accounts["ACC-1002"]["balance"], 8500.00)


# ================================================================ fallback to rules
class LLMFallbackTest(LLMTestBase):
    TEXT = "What's my checking balance?"
    EXPECTED = "The balance of checking account ACC-1001 is $2,450.00."

    def assertFellBackToRules(self, app):
        reply = app.chat(ALICE, ALICE_PIN, self.TEXT)
        self.assertEqual(reply, self.EXPECTED)
        acts, obs = self.parse_events(app.tracer)
        self.assertEqual(acts[0]["args"]["mode"], "llm")
        self.assertEqual(obs[0]["result"]["intent"], "check_balance")
        # every fallback is recorded in the trace as a Concierge thought
        self.assertEqual(len(self.fallback_thoughts(app.tracer)), 1)
        return reply

    def test_garbage_http_body(self):
        self.reply_with(raw=b"<html>this is not json</html>")
        self.assertFellBackToRules(H.new_app())

    def test_http_error_status(self):
        self.reply_with(raw=b'{"error": "model overloaded"}', status=500)
        self.assertFellBackToRules(H.new_app())

    def test_response_missing_choices(self):
        self.reply_with(raw=b'{"unexpected": true}')
        self.assertFellBackToRules(H.new_app())

    def test_content_that_is_not_json(self):
        # chat() succeeds, but the model answered in prose
        self.reply_with("I'm sorry, I can't help with banking questions.")
        self.assertFellBackToRules(H.new_app())

    def test_content_with_broken_json(self):
        # braces are present, so json.loads runs and raises ValueError
        self.reply_with('{"intent": "check_balance",, }')
        self.assertFellBackToRules(H.new_app())

    def test_truncated_json(self):
        # no closing brace: there is no JSON object to parse
        self.reply_with('{"intent": "check_balance", ')
        self.assertFellBackToRules(H.new_app())

    def test_json_without_intent(self):
        self.reply_with(json.dumps({"account_type": "savings"}))
        self.assertFellBackToRules(H.new_app())

    def test_unreachable_url(self):
        self.use_llm(f"http://127.0.0.1:{_closed_port()}/v1")
        app = H.new_app()
        self.assertTrue(app.tracer.meta["concierge_mode"].startswith("llm"))
        self.assertFellBackToRules(app)
        self.assertEqual(self.server.requests, [])

    def test_chat_raises_llm_unavailable(self):
        self.use_llm(f"http://127.0.0.1:{_closed_port()}/v1")
        with self.assertRaises(llm.LLMUnavailable):
            llm.chat("system", "user", timeout=5)


# ===================================================================== regressions
class LLMRegressionTest(LLMTestBase):
    """Bugs found in the first round of testing; each must stay fixed."""

    BALANCE_TEXT = "What's my checking balance?"
    BALANCE_REPLY = "The balance of checking account ACC-1001 is $2,450.00."

    def test_string_false_skip_review_does_not_take_express_path(self):  # P8, P9
        self.reply_with(json.dumps({"intent": "transfer", "to_account": "ACC-2001",
                                    "amount": "50", "skip_review": "false"}))
        app = H.new_app()
        reply = app.chat(ALICE, ALICE_PIN, "pay Bob fifty bucks")
        self.assertTrue(reply.startswith("Done. Sent $50.00 from ACC-1001 to ACC-2001"), reply)
        _, obs = self.parse_events(app.tracer)
        self.assertIs(obs[0]["result"]["skip_review"], False)
        self.assertEqual(obs[0]["result"]["amount"], 50.0)
        # RiskAgent was consulted and its approval was used
        [assess] = H.messages(app.tracer, to="RiskAgent", performative="assess_transfer")
        self.assertEqual(assess["payload"]["amount"], 50.0)
        [execute] = H.messages(app.tracer, to="AccountAgent", performative="execute_transfer")
        aid = execute["payload"]["approval_id"]
        self.assertIsNotNone(aid)
        self.assertTrue(app.bank.approvals[aid]["used"])
        self.assertFalse(any("express path" in e["content"]
                             for e in H.events(app.tracer, "thought", "ConciergeAgent")))
        self.assertEqual(app.bank.accounts["ACC-1001"]["balance"], 2400.00)

    def test_string_amount_with_symbols_is_converted(self):
        self.reply_with(json.dumps({"intent": "transfer", "to_account": "acc-2001",
                                    "amount": "$1,200.50"}))
        app = H.new_app()
        reply = app.chat(ALICE, ALICE_PIN, "send Bob twelve hundred and fifty cents")
        self.assertIn("Please confirm: send $1,200.50 from ACC-1001 to ACC-2001", reply)

    def test_garbage_amount_asks_for_amount(self):
        self.reply_with(json.dumps({"intent": "transfer", "to_account": "ACC-2001", "amount": "lots"}))
        app = H.new_app()
        reply = app.chat(ALICE, ALICE_PIN, "send Bob lots")
        self.assertTrue(reply.startswith("Please tell me the amount"), reply)
        self.assertEqual(H.messages(app.tracer, to="RiskAgent"), [])

    def test_llm_own_account_transfer_by_type(self):
        self.reply_with(json.dumps({"intent": "transfer", "from_type": "Checking",
                                    "to_type": "SAVINGS", "amount": 300}))
        app = H.new_app()
        reply = app.chat(ALICE, ALICE_PIN, "put three hundred into my rainy-day pot")
        self.assertTrue(reply.startswith("Done. Sent $300.00 from ACC-1001 to ACC-1002"), reply)

    def test_null_content_raises_llm_unavailable(self):
        for content in (None, 42, {"intent": "help"}, ["help"]):
            with self.subTest(content=content):
                self.server.respond = lambda c=content: _completion(c)
                with self.assertRaises(llm.LLMUnavailable):
                    llm.chat("system", "user", timeout=5)

    def test_null_content_falls_back_to_rules(self):
        self.reply_with(None)
        app = H.new_app()
        self.assertEqual(app.chat(ALICE, ALICE_PIN, self.BALANCE_TEXT), self.BALANCE_REPLY)
        self.assertEqual(len(self.fallback_thoughts(app.tracer)), 1)
        self.assertEqual(len(self.server.requests), 1)

    def test_unhashable_intent_falls_back_to_rules(self):
        for intent in (["check_balance"], {"name": "check_balance"}):
            with self.subTest(intent=intent):
                self.reply_with(json.dumps({"intent": intent}))
                app = H.new_app()
                self.assertEqual(app.chat(ALICE, ALICE_PIN, self.BALANCE_TEXT), self.BALANCE_REPLY)
                self.assertEqual(len(self.fallback_thoughts(app.tracer)), 1)


class NoLLMConfiguredTest(_path.RulesOnlyTestCase, unittest.TestCase):
    def test_rules_mode_without_env(self):
        self.assertIsNone(llm.llm_config())
        app = H.new_app()
        self.assertEqual(app.tracer.meta["concierge_mode"], "rules")
        app.chat(ALICE, ALICE_PIN, "help")
        self.assertEqual(H.actions(app.tracer, "parse_request")[0]["args"]["mode"], "rules")
        with self.assertRaises(llm.LLMUnavailable):
            llm.chat("system", "user")

    def test_model_without_base_url_is_not_enough(self):
        with mock.patch.dict(os.environ, {"BANKASSIST_LLM_MODEL": MODEL}):
            self.assertIsNone(llm.llm_config())


if __name__ == "__main__":
    unittest.main()
