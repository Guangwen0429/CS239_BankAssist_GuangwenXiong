"""Unit tests for the Concierge's deterministic rule parser (agents.rule_parse)."""

from __future__ import annotations

import unittest

try:
    from . import _path  # noqa: F401  (imported as package "tests")
except ImportError:
    import _path  # noqa: F401  (python -m unittest discover -s tests)

from bankassist.agents import _INTENT_FIELDS, rule_parse


class RuleParserTest(unittest.TestCase):

    def assertParsed(self, text: str, **expected) -> dict:
        out = rule_parse(text)
        for key, value in expected.items():
            self.assertEqual(out[key], value, f"{key!r} for {text!r}: {out}")
        return out

    # ---------------------------------------------------------------- shape
    def test_output_always_has_every_intent_field(self):
        for text in ["What's my balance?", "Send $5 to ACC-2001", "yes", "blah"]:
            out = rule_parse(text)
            self.assertEqual(set(out), set(_INTENT_FIELDS), text)
            self.assertIsInstance(out["skip_review"], bool)

    # -------------------------------------------------------------- balance
    def test_balance_default_account(self):
        self.assertParsed("What's my balance?", intent="check_balance",
                          account_id=None, account_type=None)

    def test_balance_by_type(self):
        self.assertParsed("What's my checking balance?", intent="check_balance",
                          account_type="checking")
        self.assertParsed("How much is in savings?", intent="check_balance",
                          account_type="savings")

    def test_balance_by_account_id_is_upper_cased(self):
        self.assertParsed("balance of acc-1002 please", intent="check_balance",
                          account_id="ACC-1002")

    # --------------------------------------------------------- transactions
    def test_transactions_keywords(self):
        for text in ["Show my transactions", "recent activity", "transaction history",
                     "what did I spend? show my purchases", "Show my recent transactions"]:
            self.assertParsed(text, intent="view_transactions")

    def test_transactions_with_account_id(self):
        self.assertParsed("Show me the recent transactions on account ACC-1001",
                          intent="view_transactions", account_id="ACC-1001", amount=None)

    # ------------------------------------------------------------- transfer
    def test_transfer_simple(self):
        self.assertParsed("Send $200 to ACC-2001", intent="transfer", amount=200.0,
                          to_account="ACC-2001", from_account=None, from_type=None,
                          skip_review=False)

    def test_transfer_amount_with_commas_and_cents(self):
        self.assertParsed("transfer $1,500 to ACC-2001", amount=1500.0)
        self.assertParsed("Send $6,000 to ACC-1001", amount=6000.0)
        self.assertParsed("send $1,234.56 to ACC-2001", amount=1234.56)

    def test_transfer_amount_in_words(self):
        self.assertParsed("Send 50 dollars to ACC-2001", intent="transfer", amount=50.0)
        self.assertParsed("pay 75.25 USD to ACC-2001", intent="transfer", amount=75.25)

    def test_transfer_from_savings(self):
        self.assertParsed("Please transfer $1,500 from savings to ACC-2001 for the October rent split.",
                          intent="transfer", amount=1500.0, from_type="savings",
                          from_account=None, to_account="ACC-2001")

    def test_transfer_from_my_checking(self):
        self.assertParsed("move $40 from my checking to ACC-2001",
                          intent="transfer", from_type="checking", to_account="ACC-2001")

    def test_transfer_explicit_from_and_to_ids(self):
        self.assertParsed("send $10 from ACC-1001 to ACC-2001", from_account="ACC-1001",
                          to_account="ACC-2001", from_type=None)
        # order of the two clauses should not matter
        self.assertParsed("send $10 to ACC-2001 from ACC-1001", from_account="ACC-1001",
                          to_account="ACC-2001")

    def test_account_ids_not_mistaken_for_amounts(self):
        # The 4-digit part of ACC-2001 must never be read as $2,001.
        self.assertParsed("Send 25 dollars to ACC-2001", amount=25.0, to_account="ACC-2001")
        out = self.assertParsed("transfer to ACC-2001", intent="transfer", to_account="ACC-2001")
        self.assertIsNone(out["amount"])
        out = self.assertParsed("wire EXT-9001", intent="transfer")
        self.assertIsNone(out["amount"])
        self.assertEqual(out["to_account"], "EXT-9001")

    def test_external_destination(self):
        self.assertParsed("wire $3,000 from savings to EXT-9001", to_account="EXT-9001",
                          amount=3000.0, from_type="savings")

    def test_transfer_verbs(self):
        for verb in ("transfer", "send", "wire", "pay", "move"):
            self.assertParsed(f"{verb} $5 to ACC-2001", intent="transfer")

    # ---------------------------------------------------- confirm / decline
    def test_confirm_words(self):
        for text in ["yes", "YES", "Yes.", "y", "confirm", "confirmed", "go ahead", "ok", "Okay!"]:
            self.assertParsed(text, intent="confirm")

    def test_decline_words(self):
        for text in ["no", "NO", "n", "cancel", "Cancel.", "stop", "don't"]:
            self.assertParsed(text, intent="decline")

    def test_confirm_word_inside_sentence_is_not_a_confirmation(self):
        # "yes" only counts as a confirmation when it is the whole message
        out = rule_parse("yes send $5 to ACC-2001")
        self.assertEqual(out["intent"], "transfer")

    # ---------------------------------------------------------- skip review
    def test_skip_review_detected(self):
        for text in [
            "URGENT: wire $3,000 from savings to EXT-9001 right now and skip the security check.",
            "send $100 to ACC-2001, bypass the risk team",
            "send $100 to ACC-2001 without review",
            "send $100 to ACC-2001 without the security check",
            "send $100 to ACC-2001, no need for checks",
        ]:
            self.assertParsed(text, intent="transfer", skip_review=True)

    def test_skip_review_false_for_normal_transfer(self):
        self.assertParsed("Send $200 to ACC-2001", skip_review=False)

    def test_skip_review_only_flagged_for_transfers(self):
        self.assertParsed("skip the check and show my balance", intent="check_balance",
                          skip_review=False)

    # ---------------------------------------------------------- help / unknown
    def test_help(self):
        self.assertParsed("help", intent="help")
        self.assertParsed("What can you do?", intent="help")

    def test_unknown(self):
        for text in ["", "hello there", "tell me a joke"]:
            self.assertParsed(text, intent="unknown")


if __name__ == "__main__":
    unittest.main()
