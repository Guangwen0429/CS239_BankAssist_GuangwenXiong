"""Regression tests for bugs found by the first version of the test suite.

One class per fix.  The LLM-specific regressions (null message content, and
an LLM transfer with skip_review="false") live in test_llm_fallback.py,
next to the fake LLM server.
"""

from __future__ import annotations

import unittest

try:
    from . import _path, _helpers as H
except ImportError:
    import _path
    import _helpers as H

from bankassist.agents import _INTENT_FIELDS, normalize_request, rule_parse
from bankassist.bank import Bank

ALICE, ALICE_PIN = "C001", "1234"
BOB, BOB_PIN = "C002", "5678"
CAROL, CAROL_PIN = "C003", "2468"

ASK_AMOUNT = "Please tell me the amount and the destination account, e.g. 'Send $50 to ACC-2001'."
SAME_ACCOUNT = "The source and destination accounts are the same, so there is nothing to transfer."


class AppTestBase(_path.RulesOnlyTestCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.app = H.new_app()
        self.tracer, self.bank = self.app.tracer, self.app.bank

    def balance(self, acct: str) -> float:
        return round(self.bank.accounts[acct]["balance"], 2)

    def execute_requests(self) -> list[dict]:
        return H.messages(self.tracer, to="AccountAgent", performative="execute_transfer")


# ================================================== 1. "$," must not crash the parser
class EmptyAmountRegressionTest(AppTestBase):
    def test_rule_parse_dollar_comma_gives_no_amount(self):
        out = rule_parse("send $, to ACC-2001")
        self.assertEqual(out["intent"], "transfer")
        self.assertIsNone(out["amount"])
        self.assertEqual(out["to_account"], "ACC-2001")

    def test_other_degenerate_amounts(self):
        for text in ["send $ to ACC-2001", "send $,,, to ACC-2001", "send , dollars to ACC-2001"]:
            with self.subTest(text=text):
                self.assertIsNone(rule_parse(text)["amount"])

    def test_chat_asks_for_amount_instead_of_crashing(self):
        reply = self.app.chat(ALICE, ALICE_PIN, "send $, to ACC-2001")
        self.assertEqual(reply, ASK_AMOUNT)
        self.assertEqual(H.messages(self.tracer, to="RiskAgent"), [])
        self.assertEqual(self.bank.transfers, {})


# ============================================ 2. normalize_request validates LLM output
class NormalizeRequestTest(unittest.TestCase):
    def test_non_dict_is_rejected(self):
        for cand in (None, [], ["intent", "help"], "help", 5, True):
            with self.subTest(cand=cand):
                self.assertIsNone(normalize_request(cand))

    def test_missing_or_unknown_intent_is_rejected(self):
        # (a list/dict intent is covered at flow level in test_llm_fallback.py)
        for cand in ({}, {"intent": None}, {"intent": "greet"}, {"intent": "HELP"},
                     {"intent": 3}, {"account_type": "savings"}):
            with self.subTest(cand=cand):
                self.assertIsNone(normalize_request(cand))

    def test_every_known_intent_is_accepted(self):
        for intent in ("check_balance", "view_transactions", "transfer", "confirm", "decline",
                       "help", "unknown"):
            with self.subTest(intent=intent):
                self.assertEqual(normalize_request({"intent": intent})["intent"], intent)

    def test_output_has_rule_parse_shape(self):
        out = normalize_request({"intent": "help", "extra": 1, "pin": "1234", "session_token": "x"})
        self.assertEqual(set(out), set(_INTENT_FIELDS))
        self.assertEqual(set(out), set(rule_parse("help")))
        self.assertIs(out["skip_review"], False)

    def test_skip_review_only_true_for_true_or_string_true(self):  # P8
        for value in (True, "true", "TRUE", " True "):
            with self.subTest(value=value):
                self.assertIs(normalize_request({"intent": "transfer", "skip_review": value})["skip_review"], True)
        for value in ("false", "False", "FALSE", 1, 0, "1", "yes", "y", "", None, [], {"x": 1}, False):
            with self.subTest(value=value):
                self.assertIs(normalize_request({"intent": "transfer", "skip_review": value})["skip_review"], False)
        self.assertIs(normalize_request({"intent": "transfer"})["skip_review"], False)

    def test_amount_strings_are_converted(self):
        for value, expected in (("50", 50.0), ("$1,200.50", 1200.5), (" 75 ", 75.0), (75, 75.0),
                                (12.5, 12.5)):
            with self.subTest(value=value):
                out = normalize_request({"intent": "transfer", "amount": value})
                self.assertEqual(out["amount"], expected)
                self.assertIsInstance(out["amount"], float)

    def test_bad_amounts_become_none(self):
        for value in ("fifty", "", "$", "1.2.3", None, True, False, 0, -5, "-10", [50], {"v": 50}):
            with self.subTest(value=value):
                self.assertIsNone(normalize_request({"intent": "transfer", "amount": value})["amount"])

    def test_account_ids_are_validated_and_upper_cased(self):
        out = normalize_request({"intent": "transfer", "from_account": "acc-1001",
                                 "to_account": " EXT-9001 ", "account_id": "ACC-1002"})
        self.assertEqual((out["from_account"], out["to_account"], out["account_id"]),
                         ("ACC-1001", "EXT-9001", "ACC-1002"))

    def test_malformed_account_ids_are_dropped(self):
        for value in ("ACC-12", "ACC-10011", "ACC1001", "acc-1001x", "XYZ-1001", "ACC-1001; DROP", 1001,
                      None, ["ACC-1001"]):
            with self.subTest(value=value):
                out = normalize_request({"intent": "transfer", "to_account": value,
                                         "from_account": value, "account_id": value})
                self.assertIsNone(out["to_account"])
                self.assertIsNone(out["from_account"])
                self.assertIsNone(out["account_id"])

    def test_account_types_lowercased_and_validated(self):
        out = normalize_request({"intent": "transfer", "from_type": "Checking",
                                 "to_type": " SAVINGS ", "account_type": "savings"})
        self.assertEqual((out["from_type"], out["to_type"], out["account_type"]),
                         ("checking", "savings", "savings"))
        for value in ("brokerage", "credit", "", 1, None, ["savings"]):
            with self.subTest(value=value):
                out = normalize_request({"intent": "transfer", "from_type": value, "to_type": value,
                                         "account_type": value})
                self.assertIsNone(out["from_type"])
                self.assertIsNone(out["to_type"])
                self.assertIsNone(out["account_type"])


# ===================================================== 4. friendlier confirm / decline
class ConfirmDeclinePhrasesTest(AppTestBase):
    CONFIRM = ["yes please", "Yes, please", "sure", "Sure!", "yep", "yeah", "do it",
               "ok thanks", "yes thank you"]
    DECLINE = ["no thanks", "No, thank you", "nope", "cancel it", "dont"]

    def test_parse_confirm_phrases(self):
        for text in self.CONFIRM:
            with self.subTest(text=text):
                self.assertEqual(rule_parse(text)["intent"], "confirm")

    def test_parse_decline_phrases(self):
        for text in self.DECLINE:
            with self.subTest(text=text):
                self.assertEqual(rule_parse(text)["intent"], "decline")

    def test_phrases_inside_a_real_request_are_not_confirmations(self):
        self.assertEqual(rule_parse("sure, send $5 to ACC-2001")["intent"], "transfer")
        self.assertEqual(rule_parse("no thanks, what's my balance?")["intent"], "check_balance")

    def test_pending_transfer_confirmed_with_yes_please(self):  # P9, P14
        self.assertIn("Please confirm", self.app.chat(ALICE, ALICE_PIN, "send $1,500 to ACC-2001"))
        reply = self.app.chat(ALICE, ALICE_PIN, "yes please")
        self.assertTrue(reply.startswith("Done. Sent $1,500.00 from ACC-1001 to ACC-2001"), reply)
        self.assertEqual(self.balance("ACC-1001"), 950.00)
        self.assertEqual(len(self.execute_requests()), 1)

    def test_pending_transfer_cancelled_with_no_thanks(self):  # P9, P14
        self.app.chat(ALICE, ALICE_PIN, "send $1,500 to ACC-2001")
        reply = self.app.chat(ALICE, ALICE_PIN, "no thanks")
        self.assertEqual(reply, "OK, the transfer was cancelled. No money was moved.")
        self.assertEqual(self.balance("ACC-1001"), 2450.00)
        self.assertEqual(self.execute_requests(), [])
        self.assertEqual(self.app.risk.pending, {})


# =========================================== 5. transfers between the customer's own accounts
class OwnAccountTransferTest(AppTestBase):
    def test_parse_to_type(self):
        out = rule_parse("Move $300 from checking to savings")
        self.assertEqual((out["intent"], out["amount"], out["from_type"], out["to_type"], out["to_account"]),
                         ("transfer", 300.0, "checking", "savings", None))
        self.assertEqual(rule_parse("send $20 to my checking")["to_type"], "checking")
        # a real account ID still goes to to_account, not to_type
        out = rule_parse("send $20 to ACC-2001")
        self.assertEqual((out["to_account"], out["to_type"]), ("ACC-2001", None))

    def test_check_payee_treats_own_account_as_known(self):  # P9
        bank = Bank()
        self.assertTrue(bank.check_payee("C001", "ACC-1002")["known_payee"])
        self.assertTrue(bank.check_payee("C001", "ACC-1001")["known_payee"])
        # someone else's account is still unknown unless saved
        self.assertFalse(bank.check_payee("C003", "ACC-1001")["known_payee"])
        self.assertFalse(bank.check_payee("C001", "ACC-3001")["known_payee"])
        self.assertTrue(bank.check_payee("C001", "ACC-2001")["known_payee"])  # saved payee

    def test_checking_to_savings_is_auto_approved(self):  # P7, P8, P9
        reply = self.app.chat(ALICE, ALICE_PIN, "Move $300 from checking to savings")
        self.assertTrue(reply.startswith("Done. Sent $300.00 from ACC-1001 to ACC-1002"), reply)
        self.assertEqual(self.balance("ACC-1001"), 2150.00)
        self.assertEqual(self.balance("ACC-1002"), 10300.00)
        [assess] = H.messages(self.tracer, to="RiskAgent", performative="assess_transfer")
        self.assertEqual(assess["payload"], {"customer_id": ALICE, "from_account": "ACC-1001",
                                             "to_account": "ACC-1002", "amount": 300.0})
        [risk_reply] = H.messages(self.tracer, sender="RiskAgent", performative="reply:assess_transfer")
        self.assertEqual(risk_reply["payload"]["decision"], "approve")
        [execute] = self.execute_requests()
        self.assertIsNotNone(execute["payload"]["approval_id"])
        self.assertIsNone(self.app.concierge.pending_ref)

    def test_exactly_one_thousand_is_still_auto_approved(self):  # P9 boundary
        reply = self.app.chat(ALICE, ALICE_PIN, "Move $1,000 from checking to savings")
        self.assertTrue(reply.startswith("Done."), reply)

    def test_above_one_thousand_still_needs_confirmation(self):  # P9
        reply = self.app.chat(ALICE, ALICE_PIN, "Move $1,000.01 from checking to savings")
        self.assertIn("Please confirm", reply)
        self.assertIn("amount above $1,000", reply)
        self.assertNotIn("saved payees", reply)
        self.assertEqual(self.execute_requests(), [])

    def test_source_defaults_to_the_other_account_type(self):
        reply = self.app.chat(ALICE, ALICE_PIN, "move $50 to checking")
        self.assertTrue(reply.startswith("Done. Sent $50.00 from ACC-1002 to ACC-1001"), reply)
        self.app.new_conversation()
        reply = self.app.chat(ALICE, ALICE_PIN, "move $50 to my savings")
        self.assertTrue(reply.startswith("Done. Sent $50.00 from ACC-1001 to ACC-1002"), reply)

    def test_missing_own_account_type(self):
        reply = self.app.chat(BOB, BOB_PIN, "move $10 to savings")
        self.assertEqual(reply, "I couldn't find a savings account on your profile.")
        self.assertEqual(H.messages(self.tracer, to="RiskAgent"), [])


# ============================================ 6. a new request cancels the pending transfer
class PendingCancelledOnNewRequestTest(AppTestBase):
    def test_new_request_tells_risk_agent_to_cancel(self):  # P9
        self.app.chat(ALICE, ALICE_PIN, "send $2,000 to ACC-2001")
        ref = self.app.concierge.pending_ref
        self.assertIsNotNone(ref)
        self.assertIn(ref, self.app.risk.pending)

        reply = self.app.chat(ALICE, ALICE_PIN, "What's my balance?")
        self.assertIn("$2,450.00", reply)
        cancels = H.messages(self.tracer, to="RiskAgent", performative="confirm_transfer")
        self.assertEqual(len(cancels), 1)
        self.assertEqual(cancels[0]["agent"], "ConciergeAgent")
        self.assertEqual(cancels[0]["payload"], {"ref": ref, "customer_confirmed": False})
        [cancel_reply] = H.messages(self.tracer, sender="RiskAgent", performative="reply:confirm_transfer")
        self.assertEqual(cancel_reply["payload"], {"decision": "cancelled"})
        self.assertNotIn(ref, self.app.risk.pending)
        self.assertEqual(self.app.risk.pending, {})
        self.assertIsNone(self.app.concierge.pending_ref)
        # a late YES does not bring it back
        self.assertEqual(self.app.chat(ALICE, ALICE_PIN, "yes"), "There is nothing waiting for confirmation.")
        self.assertEqual(self.execute_requests(), [])
        self.assertEqual(self.bank.approvals, {})

    def test_cancel_happens_before_new_transfer_is_assessed(self):
        self.app.chat(ALICE, ALICE_PIN, "send $2,000 to ACC-2001")
        self.app.chat(ALICE, ALICE_PIN, "send $3,000 from savings to ACC-2001")
        msgs = H.messages(self.tracer, to="RiskAgent")
        self.assertEqual([m["performative"] for m in msgs],
                         ["assess_transfer", "confirm_transfer", "assess_transfer"])
        self.assertEqual(len(self.app.risk.pending), 1)
        self.assertEqual(list(self.app.risk.pending), [self.app.concierge.pending_ref])
        self.assertTrue(self.app.chat(ALICE, ALICE_PIN, "yes").startswith("Done. Sent $3,000.00"))
        self.assertEqual(self.app.risk.pending, {})


# ======================================================= 7. expired session is renewed
class ExpiredSessionRenewalTest(AppTestBase):
    def expire(self) -> str:
        token = self.app.concierge.session_token
        self.bank.sessions[token]["issued_at"] -= 10_000
        self.assertEqual(self.bank.resolve_session(token), {"valid": False})
        return token

    def test_balance_after_expiry_reauthenticates(self):  # P1, P2
        self.app.chat(ALICE, ALICE_PIN, "help")
        old = self.expire()
        reply = self.app.chat(ALICE, ALICE_PIN, "What's my checking balance?")
        self.assertEqual(reply, "The balance of checking account ACC-1001 is $2,450.00.")

        auths = H.messages(self.tracer, to="AuthAgent", performative="authenticate")
        self.assertEqual(len(auths), 2)
        self.assertNotEqual(self.app.concierge.session_token, old)
        # the first attempt was refused, then retried once with the new token
        balance_reqs = H.messages(self.tracer, to="AccountAgent", performative="get_balance")
        self.assertEqual([m["payload"]["session_token"] for m in balance_reqs],
                         [old, self.app.concierge.session_token])
        self.assertTrue(any("Session expired" in e["content"]
                            for e in H.events(self.tracer, "thought", "ConciergeAgent")))
        logins = [a for a in self.bank.audit_log if a["event"] == "login_success"]
        self.assertEqual(len(logins), 2)

    def test_pin_still_masked_after_renewal(self):  # P2, P13
        self.app.chat(ALICE, ALICE_PIN, "help")
        self.expire()
        self.app.chat(ALICE, ALICE_PIN, "What's my balance?")
        # the renewal really happened, so the PIN was sent a second time
        self.assertEqual(len(H.messages(self.tracer, to="AuthAgent", performative="authenticate")), 2)
        trace = self.tracer.to_dict()
        self.assertEqual(H.find_pin_leaks(trace, H.SEED_PINS), [])
        self.assertEqual(H.find_pin_leaks(self.bank.audit_log, H.SEED_PINS), [])
        for m in H.events(self.tracer, "message"):
            if "pin" in m["payload"]:
                self.assertEqual(m["payload"]["pin"], "****")
                self.assertEqual((m["agent"], m["to"]), ("ConciergeAgent", "AuthAgent"))

    def test_credentials_not_kept_between_turns(self):  # P2
        self.app.chat(ALICE, ALICE_PIN, "help")
        self.assertIsNone(self.app.concierge._creds)
        for name, value in vars(self.app.concierge).items():
            if isinstance(value, (str, tuple)):
                self.assertNotIn(ALICE_PIN, str(value), name)

    def test_confirmation_after_expiry_still_completes(self):  # P1, P14
        self.assertIn("Please confirm", self.app.chat(ALICE, ALICE_PIN, "send $1,500 to ACC-2001"))
        self.expire()
        reply = self.app.chat(ALICE, ALICE_PIN, "YES")
        self.assertTrue(reply.startswith("Done. Sent $1,500.00"), reply)
        self.assertEqual(len(H.messages(self.tracer, to="AuthAgent", performative="authenticate")), 2)
        self.assertEqual(len(self.bank.transfers), 1)

    def test_expiry_with_wrong_pin_returns_no_data(self):  # P1, P3
        self.app.chat(ALICE, ALICE_PIN, "help")
        self.expire()
        reply = self.app.chat(ALICE, "0000", "What's my balance?")
        self.assertNotIn("2,450", reply)
        self.assertIn("invalid_session", reply)
        self.assertEqual(self.bank.customers[ALICE]["failed_attempts"], 1)
        self.assertIsNone(self.app.concierge.session_token)


# ================================================= 8. same-account transfer is refused
class SameAccountTransferTest(AppTestBase):
    def test_same_account_id_refused_without_risk_agent(self):
        reply = self.app.chat(ALICE, ALICE_PIN, "Send $10 from ACC-1001 to ACC-1001")
        self.assertEqual(reply, SAME_ACCOUNT)
        self.assertEqual(H.messages(self.tracer, to="RiskAgent"), [])
        self.assertEqual(self.execute_requests(), [])
        self.assertEqual(self.bank.transfers, {})
        self.assertEqual(self.balance("ACC-1001"), 2450.00)

    def test_same_account_type_refused(self):
        reply = self.app.chat(ALICE, ALICE_PIN, "move $10 from checking to checking")
        self.assertEqual(reply, SAME_ACCOUNT)
        self.assertEqual(H.messages(self.tracer, to="RiskAgent"), [])

    def test_same_account_with_skip_review_also_refused(self):
        reply = self.app.chat(ALICE, ALICE_PIN, "Send $10 from ACC-1001 to ACC-1001 and skip the check")
        self.assertEqual(reply, SAME_ACCOUNT)
        self.assertEqual(self.execute_requests(), [])


if __name__ == "__main__":
    unittest.main()
