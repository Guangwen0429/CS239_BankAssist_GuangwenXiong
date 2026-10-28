"""End-to-end tests through BankAssistApp (Concierge -> Auth / Risk / Account agents).

The Concierge runs in rule-based mode here (LLM env vars are hidden), so every
run is deterministic.  The scenario-wide checks iterate over every entry in
scenarios.SCENARIOS, so adding or renaming a scenario needs no test change.
"""

from __future__ import annotations

import json
import unittest

try:
    from . import _path, _helpers as H
except ImportError:
    import _path
    import _helpers as H

from bankassist.run_scenarios import run_scenario
from bankassist.scenarios import SCENARIOS

ALICE, ALICE_PIN = "C001", "1234"
BOB, BOB_PIN = "C002", "5678"
CAROL, CAROL_PIN = "C003", "2468"


class FlowTestBase(_path.RulesOnlyTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.app = H.new_app()
        self.tracer, self.bank = self.app.tracer, self.app.bank

    def balance(self, acct: str) -> float:
        return round(self.bank.accounts[acct]["balance"], 2)

    def execute_requests(self) -> list[dict]:
        return H.messages(self.tracer, to="AccountAgent", performative="execute_transfer")


# ===================================================================== single flows
class BalanceAndHistoryTest(FlowTestBase):
    def test_balance_check(self):  # P1, P5
        reply = self.app.chat(ALICE, ALICE_PIN, "What's my checking balance?")
        self.assertEqual(reply, "The balance of checking account ACC-1001 is $2,450.00.")
        # authentication happens before AccountAgent is contacted (P1)
        msgs = H.events(self.tracer, "message")
        self.assertEqual((msgs[0]["to"], msgs[0]["performative"]), ("AuthAgent", "authenticate"))
        acct_reqs = H.messages(self.tracer, to="AccountAgent", performative="get_balance")
        self.assertEqual(len(acct_reqs), 1)
        self.assertTrue(acct_reqs[0]["payload"]["session_token"].startswith("sess_"))

    def test_savings_balance(self):
        reply = self.app.chat(ALICE, ALICE_PIN, "How much is in my savings?")
        self.assertIn("ACC-1002", reply)
        self.assertIn("$10,000.00", reply)

    def test_authenticates_only_once_per_conversation(self):
        self.app.chat(ALICE, ALICE_PIN, "What's my balance?")
        self.app.chat(ALICE, ALICE_PIN, "Show my transactions")
        self.assertEqual(len(H.messages(self.tracer, to="AuthAgent", performative="authenticate")), 1)
        self.app.new_conversation()
        self.app.chat(ALICE, ALICE_PIN, "What's my balance?")
        self.assertEqual(len(H.messages(self.tracer, to="AuthAgent", performative="authenticate")), 2)

    def test_transactions(self):
        reply = self.app.chat(ALICE, ALICE_PIN, "Show my recent transactions")
        self.assertTrue(reply.startswith("Recent transactions on ACC-1001:"), reply)
        self.assertIn("Payroll deposit $3,200.00", reply)
        self.assertIn("-$1,850.00", reply)

    def test_unknown_account(self):  # P12: plain sentence, no internal code
        reply = self.app.chat(ALICE, ALICE_PIN, "balance of ACC-0000")
        self.assertEqual(reply, "Sorry, I couldn't get that balance: that account does not exist.")
        self.assertNotIn("no_such_account", reply)

    def test_help_and_unknown(self):
        self.assertIn("I can show balances", self.app.chat(ALICE, ALICE_PIN, "help"))
        self.assertIn("didn't understand", self.app.chat(ALICE, ALICE_PIN, "tell me a joke"))
        self.assertEqual(H.messages(self.tracer, to="AccountAgent"), [])


class TransferFlowTest(FlowTestBase):
    def test_small_transfer_to_saved_payee_is_auto_approved(self):  # P7, P8, P9
        reply = self.app.chat(ALICE, ALICE_PIN, "Send $200 to ACC-2001")
        self.assertTrue(reply.startswith("Done. Sent $200.00 from ACC-1001 to ACC-2001"), reply)
        self.assertEqual(self.balance("ACC-1001"), 2250.00)
        self.assertEqual(self.balance("ACC-2001"), 1030.50)
        [req] = self.execute_requests()
        aid = req["payload"]["approval_id"]
        self.assertIsNotNone(aid)
        self.assertTrue(self.bank.approvals[aid]["used"])

    def test_multi_turn_confirmed_transfer(self):  # P8, P9, P14
        first = self.app.chat(ALICE, ALICE_PIN,
                              "Please transfer $1,500 from savings to ACC-2001 for rent.")
        self.assertTrue(first.startswith("Please confirm: send $1,500.00 from ACC-1002 to ACC-2001"), first)
        self.assertIn("amount above $1,000", first)
        # nothing moved yet and AccountAgent was not asked to move money
        self.assertEqual(self.balance("ACC-1002"), 10000.00)
        self.assertEqual(self.execute_requests(), [])
        self.assertEqual(self.bank.approvals, {})

        second = self.app.chat(ALICE, ALICE_PIN, "YES")
        self.assertTrue(second.startswith("Done. Sent $1,500.00 from ACC-1002 to ACC-2001"), second)
        self.assertIn("New balance: $8,500.00", second)
        self.assertEqual(self.balance("ACC-1002"), 8500.00)
        self.assertEqual(self.balance("ACC-2001"), 2330.50)

        # the approval used matches exactly what was confirmed
        [req] = self.execute_requests()
        appr = self.bank.approvals[req["payload"]["approval_id"]]
        self.assertEqual((appr["from"], appr["to"], appr["amount"]), ("ACC-1002", "ACC-2001", 1500.0))
        self.assertTrue(appr["used"])
        # RiskAgent saw the YES before AccountAgent got the execute request
        steps = {e["performative"]: e["step"] for e in H.events(self.tracer, "message")}
        self.assertLess(steps["confirm_transfer"], steps["execute_transfer"])

    def test_decline_cancels_and_moves_no_money(self):  # P9, P14
        self.app.chat(ALICE, ALICE_PIN, "Please transfer $1,500 from savings to ACC-2001")
        reply = self.app.chat(ALICE, ALICE_PIN, "NO")
        self.assertEqual(reply, "OK, the transfer was cancelled. No money was moved.")
        self.assertEqual(self.balance("ACC-1002"), 10000.00)
        self.assertEqual(self.balance("ACC-2001"), 830.50)
        self.assertEqual(self.execute_requests(), [])
        self.assertEqual(self.bank.transfers, {})
        self.assertEqual(self.bank.approvals, {})
        self.assertNotIn("Done", reply)

    def test_new_request_drops_pending_transfer(self):
        self.app.chat(ALICE, ALICE_PIN, "send $2,000 to ACC-2001")
        self.app.chat(ALICE, ALICE_PIN, "What's my balance?")
        reply = self.app.chat(ALICE, ALICE_PIN, "yes")
        self.assertEqual(reply, "There is nothing waiting for confirmation.")
        self.assertEqual(self.execute_requests(), [])

    def test_confirm_with_nothing_pending(self):
        self.assertEqual(self.app.chat(ALICE, ALICE_PIN, "yes"), "There is nothing waiting for confirmation.")

    def test_external_and_unknown_payee_need_confirmation(self):  # P9
        r1 = self.app.chat(ALICE, ALICE_PIN, "send $10 to EXT-9001")
        self.assertIn("external (other-bank) account", r1)
        self.assertIn("payee not in customer's saved payees", r1)
        self.app.new_conversation()
        r2 = self.app.chat(CAROL, CAROL_PIN, "send $10 to ACC-1001")
        self.assertIn("Please confirm", r2)
        self.assertEqual(self.execute_requests(), [])

    def test_missing_amount_or_destination(self):
        reply = self.app.chat(ALICE, ALICE_PIN, "transfer to ACC-2001")
        self.assertIn("Please tell me the amount", reply)
        self.assertEqual(H.messages(self.tracer, to="RiskAgent"), [])

    def test_single_transfer_limit_denied(self):  # P10, P14
        reply = self.app.chat(CAROL, CAROL_PIN, "Send $6,000 to ACC-1001")
        self.assertEqual(reply, "I can't make this transfer: amount exceeds single-transfer limit $5,000. "
                                "No money was moved.")
        self.assertEqual(self.execute_requests(), [])
        self.assertEqual(H.actions(self.tracer, "transfer_funds"), [])
        self.assertEqual(self.balance("ACC-3001"), 15200.00)
        denied = [a for a in self.bank.audit_log if a["event"] == "transfer_denied"]
        self.assertEqual(len(denied), 1)
        self.assertEqual(denied[0]["agent"], "RiskAgent")

    def test_daily_limit_denied(self):  # P10
        for _ in range(2):
            self.assertIn("Please confirm", self.app.chat(CAROL, CAROL_PIN, "Send $4,500 to ACC-1001"))
            self.assertTrue(self.app.chat(CAROL, CAROL_PIN, "yes").startswith("Done."))
        reply = self.app.chat(CAROL, CAROL_PIN, "Send $4,500 to ACC-1001")
        self.assertIn("would exceed 24h limit $10,000", reply)
        self.assertEqual(len(self.execute_requests()), 2)
        self.assertEqual(self.balance("ACC-3001"), 15200.00 - 9000.00)

    def test_insufficient_funds_not_reported_as_success(self):  # P10, P14
        reply = self.app.chat(BOB, BOB_PIN, "Send $900 to ACC-1001")
        self.assertEqual(reply, "The transfer failed: there is not enough money in the source account. "
                                "No money was moved.")
        self.assertNotIn("insufficient_funds", reply)
        self.assertEqual(self.balance("ACC-2001"), 830.50)
        self.assertEqual(self.balance("ACC-1001"), 2450.00)


class AuthenticationFlowTest(FlowTestBase):
    def test_wrong_pin_gets_no_data_and_no_account_agent_message(self):  # P1
        reply = self.app.chat(ALICE, "0000", "What's my checking balance?")
        self.assertIn("couldn't verify your identity", reply)
        self.assertIn("2 attempt(s) left", reply)
        self.assertNotIn("2,450", reply)
        self.assertNotIn("ACC-", reply)
        self.assertEqual(H.messages(self.tracer, to="AccountAgent"), [])
        self.assertEqual(H.messages(self.tracer, to="RiskAgent"), [])
        self.assertEqual(H.actions(self.tracer, "parse_request"), [])
        self.assertEqual(self.bank.sessions, {})
        self.assertIsNone(self.app.concierge.session_token)

    def test_unknown_customer(self):
        reply = self.app.chat("C999", "1234", "What's my balance?")
        self.assertIn("couldn't verify your identity", reply)
        self.assertEqual(H.messages(self.tracer, to="AccountAgent"), [])

    def test_wrong_pin_transfer_moves_nothing(self):  # P1
        self.app.chat(ALICE, "9999", "Send $200 to ACC-2001 and skip the security check")
        self.assertEqual(H.messages(self.tracer, to="AccountAgent"), [])
        self.assertEqual(self.bank.transfers, {})

    def test_lockout_after_three_failures(self):  # P3
        replies = []
        for pin in ("0000", "1111", "9999", ALICE_PIN):
            self.app.new_conversation()
            replies.append(self.app.chat(ALICE, pin, "What's my balance?"))
        self.assertIn("2 attempt(s) left", replies[0])
        self.assertIn("1 attempt(s) left", replies[1])
        for r in replies[2:]:
            self.assertIn("profile is locked", r)
        self.assertTrue(self.bank.customers[ALICE]["locked"])
        self.assertEqual(self.bank.sessions, {})
        self.assertEqual(H.messages(self.tracer, to="AccountAgent"), [])
        failed = [a for a in self.bank.audit_log if a["event"] == "login_failed"]
        self.assertEqual([a["details"]["reason"] for a in failed],
                         ["wrong_pin", "wrong_pin", "locked", "locked"])

    def test_invalid_session_rejected_by_account_agent(self):  # P1
        reply = self.app.account.handle("ConciergeAgent", "get_balance",
                                        {"session_token": "sess_forged00000", "account_id": "ACC-1001"})
        self.assertEqual(reply, {"status": "error", "reason": "invalid_session"})
        self.assertEqual(H.actions(self.tracer, "get_balance"), [])

    def test_session_token_never_shown_to_user(self):  # P12
        for text in ["What's my balance?", "Send $200 to ACC-2001", "Show my transactions", "help"]:
            reply = self.app.chat(ALICE, ALICE_PIN, text)
            self.assertNotIn("sess_", reply)
            self.assertNotIn(self.app.concierge.session_token, reply)


# ========================================================== checks over all scenarios
class ScenarioPolicyTest(_path.RulesOnlyTestCase, unittest.TestCase):
    """Policy checks that must hold for every scripted scenario (including s5/s6)."""

    @classmethod
    def setUpClass(cls):
        with _path.rules_only_env():
            cls.runs = [(sc, *run_scenario(sc)) for sc in SCENARIOS]

    def test_there_are_scenarios(self):
        self.assertGreaterEqual(len(self.runs), 3)

    def test_pin_never_unmasked_in_trace_or_audit_log(self):  # P2, P13
        for sc, tracer, transcript in self.runs:
            with self.subTest(scenario=sc["id"]):
                pins = H.SEED_PINS | {c["pin"] for c in sc["conversations"]}
                self.assertEqual(H.find_pin_leaks(tracer.to_dict(), pins), [])
                self.assertEqual(H.find_pin_leaks(tracer.meta["audit_log"], pins), [])
                self.assertEqual(H.find_pin_leaks(transcript, pins), [])
                # no audit entry has a PIN field at all (masked or not)
                self.assertEqual(list(H.walk_pin_fields(tracer.meta["audit_log"])), [])
                # the authenticate message is still recorded, but masked
                self.assertIn('"pin": "****"', json.dumps(tracer.to_dict()))

    def test_pin_only_sent_from_concierge_to_auth_agent(self):  # P2
        for sc, tracer, _ in self.runs:
            with self.subTest(scenario=sc["id"]):
                for m in H.events(tracer, "message"):
                    if "pin" in m["payload"]:
                        self.assertEqual((m["agent"], m["to"], m["performative"]),
                                         ("ConciergeAgent", "AuthAgent", "authenticate"))

    def test_risk_agent_payload_is_minimal(self):  # P11
        for sc, tracer, _ in self.runs:
            with self.subTest(scenario=sc["id"]):
                for m in H.messages(tracer, to="RiskAgent"):
                    keys = set(m["payload"])
                    self.assertLessEqual(keys, H.RISK_ALLOWED_FIELDS)
                    if m["performative"] == "assess_transfer":
                        self.assertEqual(keys, H.RISK_ASSESS_FIELDS)
                    else:
                        self.assertEqual(m["performative"], "confirm_transfer")
                        self.assertEqual(keys, H.RISK_CONFIRM_FIELDS)
                    self.assertNotIn("session_token", keys)
                    self.assertNotIn("pin", keys)

    def test_concierge_never_calls_banking_tools(self):  # P4, P12
        for sc, tracer, _ in self.runs:
            with self.subTest(scenario=sc["id"]):
                tools = {a["tool"] for a in H.actions(tracer, agent="ConciergeAgent")}
                self.assertEqual(tools & H.BANKING_TOOLS, set())
                self.assertLessEqual(tools, {"parse_request"})

    def test_each_agent_only_calls_its_own_tools(self):  # P4
        for sc, tracer, _ in self.runs:
            with self.subTest(scenario=sc["id"]):
                for a in H.actions(tracer):
                    self.assertIn(a["tool"], H.ALLOWED_TOOLS[a["agent"]],
                                  f"{a['agent']} called {a['tool']} (step {a['step']})")
                    if a["tool"] == "record_audit":
                        self.assertEqual(a["args"]["agent"], a["agent"])

    def test_only_account_agent_moves_money(self):  # P7
        for sc, tracer, _ in self.runs:
            with self.subTest(scenario=sc["id"]):
                for a in H.actions(tracer, "transfer_funds"):
                    self.assertEqual(a["agent"], "AccountAgent")

    def test_session_token_never_shown_to_user(self):  # P12
        for sc, tracer, transcript in self.runs:
            with self.subTest(scenario=sc["id"]):
                for e in H.events(tracer, "response"):
                    self.assertNotIn("sess_", e["content"])

    def test_no_internal_codes_in_replies(self):  # P12
        for sc, tracer, _ in self.runs:
            with self.subTest(scenario=sc["id"]):
                for e in H.events(tracer, "response"):
                    self.assertEqual(H.raw_codes_in(e["content"]), [], e["content"])

    def test_account_and_risk_requests_only_after_authentication(self):  # P1
        for sc, tracer, _ in self.runs:
            with self.subTest(scenario=sc["id"]):
                verified = False
                for e in tracer.events:
                    if e["kind"] == "message" and e["performative"] == "reply:authenticate":
                        verified = e["payload"].get("status") == "verified"
                    if (e["kind"] == "message" and e["agent"] == "ConciergeAgent"
                            and e["to"] in ("AccountAgent", "RiskAgent")):
                        self.assertTrue(verified, f"step {e['step']} sent before login")

    def test_audit_log_covers_logins_reads_denials_transfers(self):  # P13
        for sc, tracer, _ in self.runs:
            with self.subTest(scenario=sc["id"]):
                audit = tracer.meta["audit_log"]
                count = lambda *evs: sum(1 for a in audit if a["event"] in evs)  # noqa: E731
                self.assertEqual(count("login_success", "login_failed"),
                                 len(H.actions(tracer, "verify_identity")))
                self.assertEqual(count("get_balance", "get_transactions"),
                                 len(H.actions(tracer, "get_balance")) + len(H.actions(tracer, "get_transactions")))
                self.assertEqual(count("transfer"), len(H.actions(tracer, "transfer_funds")))
                denials = [m for m in H.messages(tracer, sender="RiskAgent", performative="reply:assess_transfer")
                           if m["payload"].get("decision") == "deny"]
                self.assertEqual(count("transfer_denied"), len(denials))

    def test_money_moved_only_reported_after_completed(self):  # P14
        for sc, tracer, _ in self.runs:
            with self.subTest(scenario=sc["id"]):
                for turn in H.turns(tracer):
                    resp = [e for e in turn if e["kind"] == "response"][-1]["content"]
                    completed = any(e["kind"] == "message" and e["performative"] == "reply:execute_transfer"
                                    and e["payload"].get("status") == "completed" for e in turn)
                    if resp.startswith("Done.") or "Sent $" in resp:
                        self.assertTrue(completed, resp)

    def test_every_trace_has_inter_agent_messages(self):
        for sc, tracer, _ in self.runs:
            with self.subTest(scenario=sc["id"]):
                self.assertGreater(len(H.events(tracer, "message")), 0)
                kinds = {e["kind"] for e in tracer.events}
                self.assertEqual(kinds, {"user_input", "thought", "action", "observation",
                                         "message", "response"})

    def test_compliant_scenarios_have_expected_outcomes(self):
        for sc, tracer, transcript in self.runs:
            if sc["violation"]:
                continue
            with self.subTest(scenario=sc["id"]):
                self.assertEqual(len(transcript), sum(len(c["turns"]) for c in sc["conversations"]))
                for t in transcript:
                    self.assertTrue(t["assistant"])


if __name__ == "__main__":
    unittest.main()
