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

import copy

from bankassist.agents import _INTENT_FIELDS, _explain, normalize_request, rule_parse
from bankassist.app import BankAssistApp
from bankassist.bank import APPROVAL_TTL_SECONDS, SEED_DATA, Bank
from bankassist.run_scenarios import run_scenario
from bankassist.scenarios import SCENARIOS
from bankassist.trace import Tracer

ALICE, ALICE_PIN = "C001", "1234"
BOB, BOB_PIN = "C002", "5678"
CAROL, CAROL_PIN = "C003", "2468"

ASK_AMOUNT = "Please tell me the amount and the destination account, e.g. 'Send $50 to ACC-2001'."
SAME_ACCOUNT = "The source and destination accounts are the same, so there is nothing to transfer."
CANCEL_NOTICE = ("(Your transfer that was waiting for confirmation has been cancelled; "
                 "no money was moved.) ")


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
        for cand in ({}, {"intent": None}, {"intent": "greet"}, {"intent": "HELP"},
                     {"intent": 3}, {"intent": ["help"]}, {"intent": {"name": "help"}},
                     {"account_type": "savings"}):
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
        for value in ("fifty", "", "$", "1.2.3", None, True, False, 0, -5, "-10", [50], {"v": 50},
                      float("inf"), float("-inf"), float("nan"), "Infinity", "inf", "-inf", "NaN"):
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
        self.assertEqual(reply, CANCEL_NOTICE + "The balance of checking account ACC-1001 is $2,450.00.")
        cancels = H.messages(self.tracer, to="RiskAgent", performative="confirm_transfer")
        self.assertEqual(len(cancels), 1)
        self.assertEqual(cancels[0]["agent"], "ConciergeAgent")
        self.assertEqual(cancels[0]["payload"],
                         {"ref": ref, "customer_id": ALICE, "customer_confirmed": False})
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
        self.assertEqual(reply, "Sorry, I couldn't get that balance: your session could not be verified.")
        self.assertNotIn("invalid_session", reply)
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



# ############################################################################
# Second review round
# ############################################################################

# ==================================================== 9. plain-language errors (P12)
class PlainErrorMessagesTest(AppTestBase):
    def assertNoRawCode(self, reply: str) -> None:
        for code in H.RAW_ERROR_CODES:
            self.assertNotIn(code, reply)
        self.assertEqual(H.raw_codes_in(reply), [], reply)

    def test_explain_mapping(self):
        self.assertEqual(_explain("no_such_account"), "that account does not exist")
        self.assertEqual(_explain("no_account_of_type"), "there is no account of that type on your profile")
        self.assertEqual(_explain("insufficient_funds"), "there is not enough money in the source account")
        self.assertEqual(_explain("invalid_amount"), "the amount is not valid")
        self.assertEqual(_explain("invalid_session"), "your session could not be verified")
        for unknown in ("database_on_fire", None, "", 42):
            with self.subTest(code=unknown):
                self.assertEqual(_explain(unknown), "something went wrong on our side")

    def test_no_such_account_balance(self):
        reply = self.app.chat(ALICE, ALICE_PIN, "balance of ACC-0000")
        self.assertEqual(reply, "Sorry, I couldn't get that balance: that account does not exist.")
        self.assertNoRawCode(reply)

    def test_no_such_account_transactions(self):
        reply = self.app.chat(ALICE, ALICE_PIN, "show transactions for ACC-0000")
        self.assertEqual(reply, "Sorry, I couldn't get the transactions: that account does not exist.")
        self.assertNoRawCode(reply)

    def test_insufficient_funds(self):
        reply = self.app.chat(BOB, BOB_PIN, "Send $900 to ACC-1001")
        self.assertEqual(reply, "The transfer failed: there is not enough money in the source account. "
                                "No money was moved.")
        self.assertNoRawCode(reply)

    def test_invalid_amount(self):
        self.app.chat(ALICE, ALICE_PIN, "help")
        reply = self.app.concierge._execute(
            {"from_account": "ACC-1001", "to_account": "ACC-2001", "amount": 0}, approval_id=None)
        self.assertEqual(reply, "The transfer failed: the amount is not valid. No money was moved.")
        self.assertNoRawCode(reply)

    def test_no_account_of_type_balance(self):
        reply = self.app.chat(BOB, BOB_PIN, "what's my savings balance")
        self.assertEqual(reply, "Sorry, I couldn't get that balance: there is no account of that type "
                                "on your profile.")
        self.assertNoRawCode(reply)

    def test_no_raw_codes_in_any_reply_of_a_long_session(self):
        texts = ["balance of ACC-0000", "show transactions for ACC-0000", "what's my savings balance",
                 "Send $900 to ACC-1001", "send $10 to ACC-0000", "move $10 to savings", "yes", "no",
                 "help", "blah"]
        for text in texts:
            with self.subTest(text=text):
                self.assertNoRawCode(self.app.chat(BOB, BOB_PIN, text))


# =========================================== 10. AccountAgent: missing account type, audit
class AccountTypeAndAuditTest(AppTestBase):
    def test_missing_account_type_does_not_fall_back_to_checking(self):
        self.app.chat(BOB, BOB_PIN, "what's my savings balance")
        [reply] = H.messages(self.tracer, sender="AccountAgent", performative="reply:get_balance")
        self.assertEqual(reply["payload"], {"status": "error", "reason": "no_account_of_type"})
        self.assertEqual(H.actions(self.tracer, "get_balance"), [])
        self.assertEqual(H.actions(self.tracer, "get_transactions"), [])

    def test_missing_account_type_for_transactions(self):
        reply = self.app.chat(BOB, BOB_PIN, "show my savings transactions")
        self.assertEqual(reply, "Sorry, I couldn't get the transactions: there is no account of that type "
                                "on your profile.")
        self.assertNotIn("Payroll", reply)

    def test_existing_type_still_works(self):
        self.assertIn("ACC-1002", self.app.chat(ALICE, ALICE_PIN, "what's my savings balance"))

    def test_no_type_named_uses_first_account_if_no_checking(self):
        seed = copy.deepcopy(SEED_DATA)
        seed["customers"]["C004"] = {"name": "Dan", "pin": "1357", "failed_attempts": 0,
                                     "locked": False, "payees": []}
        seed["accounts"]["ACC-4001"] = {"owner": "C004", "type": "savings", "balance": 75.0}
        seed["transactions"]["ACC-4001"] = []
        app = BankAssistApp(tracer=Tracer("t"), bank=Bank(seed=seed))
        self.assertEqual(app.chat("C004", "1357", "what's my balance"),
                         "The balance of savings account ACC-4001 is $75.00.")
        app.new_conversation()
        self.assertIn("there is no account of that type",
                      app.chat("C004", "1357", "what's my checking balance"))

    def test_read_audit_entries_carry_status(self):  # P13
        self.app.chat(ALICE, ALICE_PIN, "What's my balance?")
        self.app.chat(ALICE, ALICE_PIN, "balance of ACC-0000")
        self.app.chat(ALICE, ALICE_PIN, "show transactions for ACC-1002")
        reads = [a for a in self.bank.audit_log if a["event"] in ("get_balance", "get_transactions")]
        self.assertEqual([(a["event"], a["details"]["account_id"], a["details"]["status"]) for a in reads],
                         [("get_balance", "ACC-1001", "ok"), ("get_balance", "ACC-0000", "error"),
                          ("get_transactions", "ACC-1002", "ok")])
        for a in reads:
            self.assertEqual(a["details"]["customer_id"], ALICE)

    def test_read_audit_status_in_every_scenario(self):  # P13
        for sc in SCENARIOS:
            with self.subTest(scenario=sc["id"]):
                tracer, _ = run_scenario(sc)
                for a in tracer.meta["audit_log"]:
                    if a["event"] in ("get_balance", "get_transactions"):
                        self.assertIn(a["details"]["status"], ("ok", "error"))

    def test_transfer_denied_audit_has_customer_id(self):  # P13
        self.app.chat(CAROL, CAROL_PIN, "Send $6,000 to ACC-1001")
        [denied] = [a for a in self.bank.audit_log if a["event"] == "transfer_denied"]
        self.assertEqual(denied["details"]["customer_id"], CAROL)
        self.assertEqual((denied["details"]["from"], denied["details"]["to"], denied["details"]["amount"]),
                         ("ACC-3001", "ACC-1001", 6000.0))


# ======================================================= 11. AuthAgent hardening (P1, P4)
class AuthAgentHardeningTest(AppTestBase):
    def test_customer_id_is_normalised(self):
        reply = self.app.chat("c001 ", ALICE_PIN, "What's my balance?")
        self.assertEqual(reply, "The balance of checking account ACC-1001 is $2,450.00.")
        [verify] = H.actions(self.tracer, "verify_identity")
        self.assertEqual(verify["args"]["customer_id"], ALICE)
        self.assertEqual(self.app.concierge.customer_id, ALICE)
        [login] = [a for a in self.bank.audit_log if a["event"] == "login_success"]
        self.assertEqual(login["details"]["customer_id"], ALICE)

    def test_normalised_id_counts_towards_lockout(self):  # P3
        for cid in ("c001", " C001", "c001 "):
            self.app.new_conversation()
            self.app.chat(cid, "0000", "balance")
        self.assertTrue(self.bank.customers[ALICE]["locked"])

    def test_validate_session_no_longer_supported(self):  # P4
        token = self.bank.issue_session(ALICE)["session_token"]
        reply = self.app.auth.handle("ConciergeAgent", "validate_session", {"session_token": token})
        self.assertEqual(reply["status"], "error")
        self.assertEqual(H.actions(self.tracer, "resolve_session", agent="AuthAgent"), [])

    def test_auth_agent_tool_set(self):  # P4
        self.app.chat(ALICE, ALICE_PIN, "What's my balance?")
        self.app.new_conversation()
        self.app.chat(ALICE, "0000", "What's my balance?")
        tools = {a["tool"] for a in H.actions(self.tracer, agent="AuthAgent")}
        self.assertEqual(tools, {"verify_identity", "issue_session", "record_audit"})


# ============================================ 12. RiskAgent confirmation hardening (P9, P11)
class RiskAgentConfirmationTest(AppTestBase):
    def start_pending(self, text: str = "send $2,000 to ACC-2001") -> str:
        self.assertIn("Please confirm", self.app.chat(ALICE, ALICE_PIN, text))
        return self.app.concierge.pending_ref

    def test_confirm_payload_names_the_customer(self):  # P11
        ref = self.start_pending()
        self.app.chat(ALICE, ALICE_PIN, "yes")
        [confirm] = H.messages(self.tracer, to="RiskAgent", performative="confirm_transfer")
        self.assertEqual(confirm["payload"], {"ref": ref, "customer_id": ALICE, "customer_confirmed": True})
        for m in H.messages(self.tracer, to="RiskAgent"):
            self.assertLessEqual(set(m["payload"]), H.RISK_ALLOWED_FIELDS)

    def test_approve_reply_has_no_internal_fields(self):
        self.start_pending()
        self.app.chat(ALICE, ALICE_PIN, "yes")
        [reply] = H.messages(self.tracer, sender="RiskAgent", performative="reply:confirm_transfer")
        self.assertEqual(set(reply["payload"]),
                         {"decision", "approval_id", "from_account", "to_account", "amount"})

    def test_other_customers_ref_is_denied(self):
        ref = self.start_pending()
        for cid in (BOB, None, "", "c001"):
            with self.subTest(customer_id=cid):
                reply = self.app.risk.handle("ConciergeAgent", "confirm_transfer",
                                             {"ref": ref, "customer_id": cid, "customer_confirmed": True})
                self.assertEqual(reply, {"decision": "deny", "reasons": ["unknown or expired reference"]})
        self.assertIn(ref, self.app.risk.pending)  # Alice's transfer is untouched
        self.assertEqual(self.bank.approvals, {})
        self.assertTrue(self.app.chat(ALICE, ALICE_PIN, "yes").startswith("Done. Sent $2,000.00"))

    def test_missing_customer_id_is_denied(self):
        ref = self.start_pending()
        reply = self.app.risk.handle("ConciergeAgent", "confirm_transfer",
                                     {"ref": ref, "customer_confirmed": True})
        self.assertEqual(reply["decision"], "deny")
        self.assertEqual(self.bank.approvals, {})

    def test_expired_pending_is_denied_and_discarded(self):
        ref = self.start_pending()
        self.app.risk.pending[ref]["created_at"] -= APPROVAL_TTL_SECONDS + 1
        reply = self.app.chat(ALICE, ALICE_PIN, "yes")
        self.assertEqual(reply, "The transfer could not be approved: the confirmation window "
                                "(10 minutes) has passed. No money was moved.")
        self.assertNotIn(ref, self.app.risk.pending)
        self.assertEqual(self.bank.approvals, {})
        self.assertEqual(self.execute_requests(), [])
        self.assertEqual(self.balance("ACC-1001"), 2450.00)

    def test_pending_just_inside_the_window_is_approved(self):
        ref = self.start_pending()
        self.app.risk.pending[ref]["created_at"] -= APPROVAL_TTL_SECONDS - 5
        self.assertTrue(self.app.chat(ALICE, ALICE_PIN, "yes").startswith("Done."))

    def test_refs_are_never_reused(self):
        refs = [self.start_pending()]
        self.app.chat(ALICE, ALICE_PIN, "no")                           # declined
        refs.append(self.start_pending())
        refs.append(self.start_pending("send $1,500 to ACC-2001"))      # replaces (cancels) the previous
        self.app.chat(ALICE, ALICE_PIN, "yes")                          # approved
        self.app.new_conversation()
        refs.append(self.start_pending("send $1,200 to ACC-2001"))
        self.assertEqual(refs, ["RISK-001", "RISK-002", "RISK-003", "RISK-004"])
        self.assertEqual(list(self.app.risk.pending), ["RISK-004"])


# ===================================== 13. cancellation notice and logout cancellation (P14)
class PendingCancellationNoticeTest(AppTestBase):
    def test_notice_before_new_balance_reply(self):
        self.app.chat(ALICE, ALICE_PIN, "send $2,000 to ACC-2001")
        reply = self.app.chat(ALICE, ALICE_PIN, "Show my transactions")
        self.assertTrue(reply.startswith(CANCEL_NOTICE + "Recent transactions on ACC-1001"), reply)

    def test_notice_before_new_transfer_confirmation(self):
        self.app.chat(ALICE, ALICE_PIN, "send $2,000 to ACC-2001")
        reply = self.app.chat(ALICE, ALICE_PIN, "send $1,500 to ACC-2001")
        self.assertTrue(reply.startswith(CANCEL_NOTICE + "Please confirm: send $1,500.00"), reply)

    def test_no_notice_without_pending_transfer(self):
        reply = self.app.chat(ALICE, ALICE_PIN, "What's my balance?")
        self.assertFalse(reply.startswith("("))

    def test_logout_cancels_pending_transfer(self):
        self.app.chat(ALICE, ALICE_PIN, "send $2,000 to ACC-2001")
        ref = self.app.concierge.pending_ref
        self.app.new_conversation()
        [cancel] = H.messages(self.tracer, to="RiskAgent", performative="confirm_transfer")
        self.assertEqual(cancel["payload"], {"ref": ref, "customer_id": ALICE, "customer_confirmed": False})
        self.assertEqual(self.app.risk.pending, {})
        self.assertIsNone(self.app.concierge.pending_ref)
        # the next customer cannot confirm it
        self.assertEqual(self.app.chat(BOB, BOB_PIN, "yes"), "There is nothing waiting for confirmation.")
        self.assertEqual(self.bank.approvals, {})
        self.assertEqual(self.execute_requests(), [])

    def test_cancel_pending_without_pending_sends_nothing(self):
        self.app.chat(ALICE, ALICE_PIN, "help")
        self.app.concierge.cancel_pending()
        self.app.new_conversation()
        self.assertEqual(H.messages(self.tracer, to="RiskAgent"), [])

    def test_take_back_in_same_message(self):
        text = "Can you send $100 to ACC-2001? Actually no, cancel"
        self.assertEqual(rule_parse(text)["intent"], "decline")
        reply = self.app.chat(ALICE, ALICE_PIN, text)
        self.assertEqual(reply, "There is nothing waiting for confirmation.")
        self.assertEqual(H.messages(self.tracer, to="RiskAgent"), [])
        self.assertEqual(self.bank.transfers, {})

    def test_take_back_cancels_a_pending_transfer(self):
        self.app.chat(ALICE, ALICE_PIN, "send $2,000 to ACC-2001")
        reply = self.app.chat(ALICE, ALICE_PIN, "send $3,000 to ACC-2001, never mind")
        self.assertEqual(reply, "OK, the transfer was cancelled. No money was moved.")
        self.assertEqual(len(H.messages(self.tracer, to="RiskAgent", performative="assess_transfer")), 1)
        self.assertEqual(self.app.risk.pending, {})


# ===================================================== 14. stricter rule parser
class ParserRound2Test(AppTestBase):
    def test_rejected_amounts(self):
        for amount in ("$1e3", "$10.555", "$1,,,,5", "$1,5", "$1,5000", "$5.5.5"):
            with self.subTest(amount=amount):
                self.assertIsNone(rule_parse(f"send {amount} to ACC-2001")["amount"])

    def test_accepted_amounts(self):
        for text, expected in (("send $1,000. to ACC-2001", 1000.0), ("send $200, please, to ACC-2001", 200.0),
                               ("send $1,000,000 to ACC-2001", 1_000_000.0), ("send 300 dollars to ACC-2001", 300.0),
                               ("send $ 50 to ACC-2001", 50.0), ("send $0.5 to ACC-2001", 0.5)):
            with self.subTest(text=text):
                self.assertEqual(rule_parse(text)["amount"], expected)

    def test_rejected_amount_asks_again(self):
        self.assertEqual(self.app.chat(ALICE, ALICE_PIN, "send $1e3 to ACC-2001"), ASK_AMOUNT)
        self.assertEqual(H.messages(self.tracer, to="RiskAgent"), [])

    def test_five_digit_account_is_not_truncated(self):
        out = rule_parse("send $10 to ACC-20011")
        self.assertIsNone(out["to_account"])
        self.assertEqual(self.app.chat(ALICE, ALICE_PIN, "send $10 to ACC-20011"), ASK_AMOUNT)
        self.assertEqual(self.bank.transfers, {})

    def test_two_destinations_are_ambiguous(self):
        self.assertIsNone(rule_parse("Send $10 to ACC-2001 to ACC-3001")["to_account"])
        self.assertIsNone(rule_parse("Send $10 to ACC-2001 or ACC-3001")["to_account"])
        self.assertEqual(self.app.chat(ALICE, ALICE_PIN, "Send $10 to ACC-2001 to ACC-3001"), ASK_AMOUNT)
        # the same account named twice is not ambiguous
        self.assertEqual(rule_parse("send $10 to ACC-2001, ACC-2001 is Bob")["to_account"], "ACC-2001")
        # the source does not count as a second destination
        out = rule_parse("send $10 from ACC-1001 to ACC-2001")
        self.assertEqual((out["from_account"], out["to_account"]), ("ACC-1001", "ACC-2001"))

    def test_without_checking_is_not_skip_review(self):  # P8
        out = rule_parse("pay $20 to EXT-9001 without checking")
        self.assertIs(out["skip_review"], False)
        reply = self.app.chat(ALICE, ALICE_PIN, "pay $20 to EXT-9001 without checking")
        self.assertIn("Please confirm", reply)
        self.assertEqual(len(H.messages(self.tracer, to="RiskAgent", performative="assess_transfer")), 1)

    def test_take_back_phrases(self):
        for text in ("Can you send $100 to ACC-2001? Actually no, cancel", "send $5 to ACC-2001, never mind",
                     "send $5 to ACC-2001... nevermind", "pay ACC-2001 $5, actually no",
                     "don't send $5 to ACC-2001"):
            with self.subTest(text=text):
                self.assertEqual(rule_parse(text)["intent"], "decline")
        # words that only contain "cancel" are not a take-back
        self.assertEqual(rule_parse("pay $30 to ACC-2001 for the cancelled concert")["intent"], "transfer")


# ========================================================= 15. PIN typed into the chat (P2)
class PinInChatTest(AppTestBase):
    def traced_input(self) -> str:
        return H.events(self.tracer, "user_input")[-1]["content"]

    def test_pin_masked_before_trace_and_parse(self):
        reply = self.app.chat(ALICE, ALICE_PIN, "my pin is 1234 what's my balance")
        self.assertEqual(reply, "The balance of checking account ACC-1001 is $2,450.00.")
        self.assertEqual(self.traced_input(), "my pin is **** what's my balance")
        [parse] = H.actions(self.tracer, "parse_request")
        self.assertNotIn(ALICE_PIN, parse["args"]["text"])
        self.assertEqual(H.find_pin_leaks(self.tracer.to_dict(), {ALICE_PIN}), [])

    def test_other_separators(self):
        for text, traced in (("pin=1234;balance", "pin=****;balance"), ("PIN 1234!", "PIN ****!"),
                             ("1234", "****"), ("balance (1234)", "balance (****)")):
            with self.subTest(text=text):
                self.app.chat(ALICE, ALICE_PIN, text)
                self.assertEqual(self.traced_input(), traced)

    def test_dollar_amount_equal_to_pin_is_not_masked(self):
        reply = self.app.chat(ALICE, ALICE_PIN, "Send $1234 to ACC-2001")
        self.assertEqual(self.traced_input(), "Send $1234 to ACC-2001")
        self.assertTrue(reply.startswith("Please confirm: send $1,234.00"), reply)

    def test_longer_numbers_are_not_masked(self):
        for text in ("my ref is 12345", "call 112345", "1,234 dollars balance", "12.34"):
            with self.subTest(text=text):
                self.app.chat(ALICE, ALICE_PIN, text)
                self.assertEqual(self.traced_input(), text)

    def test_only_the_session_pin_is_masked(self):
        self.app.chat(ALICE, ALICE_PIN, "is 5678 bob's pin? what's my balance")
        self.assertIn("5678", self.traced_input())

    def test_pin_followed_by_comma_is_masked(self):
        reply = self.app.chat(ALICE, ALICE_PIN, "my pin is 1234, what's my balance")
        self.assertEqual(reply, "The balance of checking account ACC-1001 is $2,450.00.")
        self.assertNotIn(ALICE_PIN, self.traced_input())
        self.assertIn("****", self.traced_input())

    def test_pin_followed_by_period_is_masked(self):
        self.app.chat(ALICE, ALICE_PIN, "what's my balance? my pin is 1234.")
        self.assertNotIn(ALICE_PIN, self.traced_input())


# ===================================== 16. negative amounts, "don't", amounts equal to the PIN
class ParserRound3Test(AppTestBase):
    def test_negative_amounts_are_not_read(self):
        for text in ("send -$5 to ACC-2001", "send -5 dollars to ACC-2001"):
            with self.subTest(text=text):
                self.assertIsNone(rule_parse(text)["amount"])
                reply = self.app.chat(ALICE, ALICE_PIN, text)
                self.assertTrue(reply.startswith("Please tell me the amount"), reply)
        self.assertEqual(self.execute_requests(), [])

    def test_dont_takes_the_request_back(self):
        before = self.balance("ACC-1001")
        self.assertEqual(rule_parse("send $50 to ACC-2001 please don't")["intent"], "decline")
        self.app.chat(ALICE, ALICE_PIN, "send $50 to ACC-2001 please don't")
        self.assertEqual(self.execute_requests(), [])
        self.assertEqual(self.balance("ACC-1001"), before)

    def test_amount_equal_to_pin_is_not_masked(self):
        reply = self.app.chat(ALICE, ALICE_PIN, "send 1234 dollars to ACC-2001")
        self.assertIn("$1,234.00", reply)

    def test_denial_says_no_money_moved(self):
        reply = self.app.chat(ALICE, ALICE_PIN, "Send $6,000 to ACC-2001")
        self.assertTrue(reply.endswith("No money was moved."), reply)


if __name__ == "__main__":
    unittest.main()
