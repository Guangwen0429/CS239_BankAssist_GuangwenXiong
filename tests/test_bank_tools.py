"""Unit tests for the mock core-banking tools in bank.py."""

from __future__ import annotations

import time
import unittest
from unittest import mock

try:
    from . import _path  # noqa: F401
except ImportError:
    import _path  # noqa: F401

from bankassist import bank as bank_mod
from bankassist.bank import (DAILY_TRANSFER_LIMIT, MAX_FAILED_PIN_ATTEMPTS, SEED_DATA,
                             SESSION_TTL_SECONDS, Bank)


class BankTestBase(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.bank = Bank()


# ===================================================================== seed data
class SeedDataTest(BankTestBase):
    def test_each_bank_is_an_independent_copy_of_the_seed(self):
        self.bank.accounts["ACC-1001"]["balance"] = 0
        self.bank.customers["C001"]["locked"] = True
        self.assertEqual(SEED_DATA["accounts"]["ACC-1001"]["balance"], 2450.00)
        self.assertFalse(SEED_DATA["customers"]["C001"]["locked"])
        self.assertEqual(Bank().accounts["ACC-1001"]["balance"], 2450.00)


# ======================================================================= identity
class VerifyIdentityTest(BankTestBase):
    def test_correct_pin(self):
        self.assertEqual(self.bank.verify_identity("C001", "1234"), {"verified": True})

    def test_unknown_customer(self):
        self.assertEqual(self.bank.verify_identity("C999", "1234"),
                         {"verified": False, "reason": "unknown_customer"})

    def test_wrong_pin_counts_down_attempts(self):
        r1 = self.bank.verify_identity("C001", "0000")
        self.assertEqual(r1, {"verified": False, "reason": "wrong_pin", "attempts_left": 2})
        r2 = self.bank.verify_identity("C001", "1111")
        self.assertEqual(r2["attempts_left"], 1)
        self.assertEqual(self.bank.customers["C001"]["failed_attempts"], 2)

    def test_correct_pin_resets_failed_counter(self):
        self.bank.verify_identity("C001", "0000")
        self.bank.verify_identity("C001", "1111")
        self.assertTrue(self.bank.verify_identity("C001", "1234")["verified"])
        self.assertEqual(self.bank.customers["C001"]["failed_attempts"], 0)
        # after a reset the customer gets the full number of attempts again
        self.assertEqual(self.bank.verify_identity("C001", "0000")["attempts_left"],
                         MAX_FAILED_PIN_ATTEMPTS - 1)

    def test_lockout_after_three_failures_refuses_correct_pin(self):  # P3
        for _ in range(MAX_FAILED_PIN_ATTEMPTS - 1):
            self.assertEqual(self.bank.verify_identity("C001", "0000")["reason"], "wrong_pin")
        third = self.bank.verify_identity("C001", "0000")
        self.assertEqual(third, {"verified": False, "reason": "locked"})
        self.assertTrue(self.bank.customers["C001"]["locked"])
        self.assertEqual(self.bank.verify_identity("C001", "1234"),
                         {"verified": False, "reason": "locked"})

    def test_lockout_is_per_customer(self):
        for _ in range(MAX_FAILED_PIN_ATTEMPTS):
            self.bank.verify_identity("C001", "0000")
        self.assertTrue(self.bank.verify_identity("C002", "5678")["verified"])


# ======================================================================= sessions
class SessionTest(BankTestBase):
    def test_issue_and_resolve(self):
        sess = self.bank.issue_session("C001")
        self.assertRegex(sess["session_token"], r"^sess_[0-9a-f]{12}$")
        self.assertEqual(sess["customer_id"], "C001")
        self.assertEqual(sess["expires_in_s"], SESSION_TTL_SECONDS)
        self.assertEqual(self.bank.resolve_session(sess["session_token"]),
                         {"valid": True, "customer_id": "C001"})

    def test_unknown_token_is_invalid(self):
        self.assertEqual(self.bank.resolve_session("sess_000000000000"), {"valid": False})
        self.assertEqual(self.bank.resolve_session(""), {"valid": False})

    def test_tokens_are_unique(self):
        tokens = {self.bank.issue_session("C001")["session_token"] for _ in range(20)}
        self.assertEqual(len(tokens), 20)

    def test_tokens_reproducible_with_same_seed(self):
        self.assertEqual(Bank().issue_session("C001")["session_token"],
                         Bank().issue_session("C001")["session_token"])

    def test_session_expires(self):
        token = self.bank.issue_session("C001")["session_token"]
        later = time.time() + SESSION_TTL_SECONDS + 1
        with mock.patch.object(bank_mod.time, "time", return_value=later):
            self.assertEqual(self.bank.resolve_session(token), {"valid": False})


# ============================================================ account read tools
class AccountReadTest(BankTestBase):
    def test_list_accounts_only_returns_own_accounts(self):
        res = self.bank.list_accounts("C001")
        self.assertEqual(res["customer_id"], "C001")
        self.assertEqual(sorted(a["account_id"] for a in res["accounts"]), ["ACC-1001", "ACC-1002"])
        self.assertEqual(self.bank.list_accounts("C999")["accounts"], [])

    def test_get_balance(self):
        self.assertEqual(self.bank.get_balance("ACC-1001"),
                         {"account_id": "ACC-1001", "type": "checking", "balance": 2450.00})

    def test_get_balance_no_such_account(self):
        self.assertEqual(self.bank.get_balance("ACC-0000"), {"error": "no_such_account"})

    def test_get_transactions_limit_and_order(self):
        res = self.bank.get_transactions("ACC-1001", limit=2)
        self.assertEqual([t["desc"] for t in res["transactions"]],
                         ["Trader Joe's", "Pharmacy - prescription"])
        self.assertEqual(len(self.bank.get_transactions("ACC-1001")["transactions"]), 4)

    def test_get_transactions_no_such_account(self):
        self.assertEqual(self.bank.get_transactions("ACC-0000"), {"error": "no_such_account"})


# ================================================================= transfer_funds
class TransferFundsTest(BankTestBase):
    def test_success_moves_money_and_records_history(self):
        res = self.bank.transfer_funds("ACC-1001", "ACC-2001", 200.0, approval_id=None)
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["new_balance"], 2250.00)
        self.assertRegex(res["transfer_id"], r"^TRF-\d{4}$")
        self.assertAlmostEqual(self.bank.accounts["ACC-1001"]["balance"], 2250.00)
        self.assertAlmostEqual(self.bank.accounts["ACC-2001"]["balance"], 1030.50)
        self.assertEqual(self.bank.transactions["ACC-1001"][-1]["amount"], -200.0)
        self.assertEqual(self.bank.transactions["ACC-2001"][-1]["amount"], 200.0)
        self.assertIn(res["transfer_id"], self.bank.transfers)

    def test_insufficient_funds(self):  # P10: no overdraft
        res = self.bank.transfer_funds("ACC-2001", "ACC-1001", 900.0)
        self.assertEqual(res, {"status": "failed", "reason": "insufficient_funds"})
        self.assertEqual(self.bank.accounts["ACC-2001"]["balance"], 830.50)
        self.assertEqual(self.bank.transfers, {})

    def test_exact_balance_is_allowed(self):
        res = self.bank.transfer_funds("ACC-2001", "ACC-1001", 830.50)
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["new_balance"], 0.0)

    def test_invalid_amount(self):
        for amt in (0, -5, -0.01):
            res = self.bank.transfer_funds("ACC-1001", "ACC-2001", amt)
            self.assertEqual(res, {"status": "failed", "reason": "invalid_amount"}, amt)
        self.assertEqual(self.bank.accounts["ACC-1001"]["balance"], 2450.00)

    def test_no_such_account(self):
        self.assertEqual(self.bank.transfer_funds("ACC-0000", "ACC-2001", 1)["reason"], "no_such_account")
        self.assertEqual(self.bank.transfer_funds("ACC-1001", "ACC-0000", 1)["reason"], "no_such_account")

    def test_fixed_today_is_used_for_transaction_dates(self):
        bank = Bank(today="2030-01-02")
        bank.transfer_funds("ACC-1001", "ACC-2001", 5.0)
        self.assertEqual(bank.transactions["ACC-1001"][-1]["date"], "2030-01-02")
        self.assertEqual(bank.transactions["ACC-2001"][-1]["date"], "2030-01-02")

    def test_default_today_is_the_current_date(self):
        self.assertIsNone(self.bank.today)
        self.bank.transfer_funds("ACC-1001", "ACC-2001", 5.0)
        self.assertEqual(self.bank.transactions["ACC-1001"][-1]["date"], time.strftime("%Y-%m-%d"))

    def test_transfer_marks_approval_used(self):
        aid = self.bank.approve_transfer("ACC-1001", "ACC-2001", 50.0)["approval_id"]
        self.bank.transfer_funds("ACC-1001", "ACC-2001", 50.0, approval_id=aid)
        self.assertTrue(self.bank.approvals[aid]["used"])
        self.assertEqual(self.bank.transfers["TRF-0001"]["approval_id"], aid)


# ===================================================================== risk tools
class RiskToolsTest(BankTestBase):
    def test_approve_transfer(self):
        res = self.bank.approve_transfer("ACC-1001", "ACC-2001", 50.0)
        self.assertEqual(res["approval_id"], "APR-0001")
        self.assertGreater(res["valid_for_s"], 0)
        appr = self.bank.approvals["APR-0001"]
        self.assertEqual((appr["from"], appr["to"], appr["amount"], appr["used"]),
                         ("ACC-1001", "ACC-2001", 50.0, False))
        self.assertEqual(self.bank.approve_transfer("ACC-1001", "ACC-2001", 1)["approval_id"], "APR-0002")

    def test_daily_total(self):
        self.assertEqual(self.bank.daily_transfer_total("ACC-1001")["total_last_24h"], 0)
        self.bank.transfer_funds("ACC-1001", "ACC-2001", 100.0)
        self.bank.transfer_funds("ACC-1001", "ACC-2001", 50.25)
        self.bank.transfer_funds("ACC-2001", "ACC-1001", 10.0)  # other source account
        self.assertEqual(self.bank.daily_transfer_total("ACC-1001"),
                         {"from_account": "ACC-1001", "total_last_24h": 150.25})

    def test_daily_total_ignores_old_transfers(self):
        self.bank.transfer_funds("ACC-1001", "ACC-2001", 100.0)
        self.bank.transfers["TRF-0001"]["time"] -= 86400 + 1
        self.assertEqual(self.bank.daily_transfer_total("ACC-1001")["total_last_24h"], 0)

    def test_daily_limit_constant(self):
        self.assertEqual(DAILY_TRANSFER_LIMIT, 10000.00)

    def test_check_payee(self):
        self.assertEqual(self.bank.check_payee("C001", "ACC-2001"),
                         {"to_account": "ACC-2001", "known_payee": True, "external": False})
        self.assertEqual(self.bank.check_payee("C001", "EXT-9001"),
                         {"to_account": "EXT-9001", "known_payee": False, "external": True})
        self.assertFalse(self.bank.check_payee("C003", "ACC-1001")["known_payee"])
        self.assertFalse(self.bank.check_payee("C999", "ACC-1001")["known_payee"])


# ====================================================================== audit log
class AuditLogTest(BankTestBase):
    def test_record_audit_appends_with_sequence_numbers(self):
        r1 = self.bank.record_audit("AuthAgent", "login_success", {"customer_id": "C001"})
        r2 = self.bank.record_audit("AccountAgent", "get_balance", {"account_id": "ACC-1001"})
        self.assertEqual(r1, {"logged": True, "seq": 1})
        self.assertEqual(r2["seq"], 2)
        self.assertEqual(self.bank.audit_log[0],
                         {"seq": 1, "agent": "AuthAgent", "event": "login_success",
                          "details": {"customer_id": "C001"}})
        self.assertEqual([e["seq"] for e in self.bank.audit_log], [1, 2])

    def test_tools_do_not_write_audit_on_their_own(self):
        # auditing is the agents' job (P13); the raw tools stay side-effect free
        self.bank.verify_identity("C001", "1234")
        self.bank.get_balance("ACC-1001")
        self.bank.transfer_funds("ACC-1001", "ACC-2001", 1.0)
        self.assertEqual(self.bank.audit_log, [])


if __name__ == "__main__":
    unittest.main()
