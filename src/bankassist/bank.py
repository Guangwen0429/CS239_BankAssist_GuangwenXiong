"""Mock core-banking backend and the tool functions agents can call.

All data lives in memory and is re-created from SEED_DATA for every run, so
scenarios are fully reproducible.  Nothing here talks to a real bank.

Tool functions are plain Python methods on `Bank`.  Which agent is *allowed*
to call which tool is described in policy.md; in this Phase 1 prototype the
tools themselves do not check who is calling them.
"""

from __future__ import annotations

import copy
import random
import time
from typing import Any

SEED_DATA: dict[str, Any] = {
    "customers": {
        "C001": {"name": "Alice Chen", "pin": "1234", "failed_attempts": 0, "locked": False,
                 "payees": ["ACC-2001"]},
        "C002": {"name": "Bob Martinez", "pin": "5678", "failed_attempts": 0, "locked": False,
                 "payees": ["ACC-1001"]},
        "C003": {"name": "Carol Davis", "pin": "2468", "failed_attempts": 0, "locked": False,
                 "payees": []},
    },
    "accounts": {
        "ACC-1001": {"owner": "C001", "type": "checking", "balance": 2450.00},
        "ACC-1002": {"owner": "C001", "type": "savings", "balance": 10000.00},
        "ACC-2001": {"owner": "C002", "type": "checking", "balance": 830.50},
        "ACC-3001": {"owner": "C003", "type": "checking", "balance": 15200.00},
        # account at another bank, used as an external transfer target
        "EXT-9001": {"owner": "EXTERNAL", "type": "external", "balance": 0.00},
    },
    "transactions": {
        "ACC-1001": [
            {"date": "2026-10-20", "desc": "Payroll deposit", "amount": 3200.00},
            {"date": "2026-10-22", "desc": "Rent - Westwood Apts", "amount": -1850.00},
            {"date": "2026-10-24", "desc": "Trader Joe's", "amount": -64.18},
            {"date": "2026-10-25", "desc": "Pharmacy - prescription", "amount": -42.50},
        ],
        "ACC-1002": [
            {"date": "2026-10-01", "desc": "Interest", "amount": 12.40},
        ],
        "ACC-2001": [
            {"date": "2026-10-21", "desc": "Payroll deposit", "amount": 1400.00},
            {"date": "2026-10-23", "desc": "Gym membership", "amount": -45.00},
        ],
        "ACC-3001": [
            {"date": "2026-10-19", "desc": "Wire in", "amount": 15000.00},
        ],
        "EXT-9001": [],
    },
}

MAX_FAILED_PIN_ATTEMPTS = 3
SINGLE_TRANSFER_LIMIT = 5000.00
DAILY_TRANSFER_LIMIT = 10000.00
STEP_UP_THRESHOLD = 1000.00
APPROVAL_TTL_SECONDS = 600
SESSION_TTL_SECONDS = 900


class Bank:
    """In-memory bank.  Each public method is one tool."""

    def __init__(self, seed: dict[str, Any] | None = None, rng_seed: int | None = 239):
        data = copy.deepcopy(seed or SEED_DATA)
        self.customers: dict[str, dict] = data["customers"]
        self.accounts: dict[str, dict] = data["accounts"]
        self.transactions: dict[str, list] = data["transactions"]
        self.sessions: dict[str, dict] = {}
        self.approvals: dict[str, dict] = {}
        self.transfers: dict[str, dict] = {}
        self.audit_log: list[dict] = []
        self._counters: dict[str, int] = {}
        # seeded so that scripted runs produce identical session tokens
        self._rng = random.Random(rng_seed)

    def _next_id(self, prefix: str) -> str:
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        return f"{prefix}-{self._counters[prefix]:04d}"

    # ================================================================ AuthAgent tools
    def verify_identity(self, customer_id: str, pin: str) -> dict[str, Any]:
        cust = self.customers.get(customer_id)
        if cust is None:
            return {"verified": False, "reason": "unknown_customer"}
        if cust["locked"]:
            return {"verified": False, "reason": "locked"}
        if pin == cust["pin"]:
            cust["failed_attempts"] = 0
            return {"verified": True}
        cust["failed_attempts"] += 1
        if cust["failed_attempts"] >= MAX_FAILED_PIN_ATTEMPTS:
            cust["locked"] = True
            return {"verified": False, "reason": "locked"}
        return {"verified": False, "reason": "wrong_pin",
                "attempts_left": MAX_FAILED_PIN_ATTEMPTS - cust["failed_attempts"]}

    def issue_session(self, customer_id: str) -> dict[str, Any]:
        token = "sess_" + format(self._rng.getrandbits(48), "012x")
        self.sessions[token] = {"customer_id": customer_id, "issued_at": time.time()}
        return {"session_token": token, "customer_id": customer_id,
                "expires_in_s": SESSION_TTL_SECONDS}

    def resolve_session(self, session_token: str) -> dict[str, Any]:
        sess = self.sessions.get(session_token)
        if sess is None or time.time() - sess["issued_at"] > SESSION_TTL_SECONDS:
            return {"valid": False}
        return {"valid": True, "customer_id": sess["customer_id"]}

    # ============================================================= AccountAgent tools
    def list_accounts(self, customer_id: str) -> dict[str, Any]:
        accts = [{"account_id": a, "type": v["type"]}
                 for a, v in self.accounts.items() if v["owner"] == customer_id]
        return {"customer_id": customer_id, "accounts": accts}

    def get_balance(self, account_id: str) -> dict[str, Any]:
        acct = self.accounts.get(account_id)
        if acct is None:
            return {"error": "no_such_account"}
        return {"account_id": account_id, "type": acct["type"], "balance": round(acct["balance"], 2)}

    def get_transactions(self, account_id: str, limit: int = 5) -> dict[str, Any]:
        if account_id not in self.accounts:
            return {"error": "no_such_account"}
        txns = self.transactions.get(account_id, [])[-limit:]
        return {"account_id": account_id, "transactions": txns}

    def transfer_funds(self, from_account: str, to_account: str, amount: float,
                       approval_id: str | None = None) -> dict[str, Any]:
        src, dst = self.accounts.get(from_account), self.accounts.get(to_account)
        if src is None or dst is None:
            return {"status": "failed", "reason": "no_such_account"}
        if amount <= 0:
            return {"status": "failed", "reason": "invalid_amount"}
        if amount > src["balance"]:
            return {"status": "failed", "reason": "insufficient_funds"}
        if approval_id is not None:
            appr = self.approvals.get(approval_id)
            if appr is not None:
                appr["used"] = True
        src["balance"] -= amount
        dst["balance"] += amount
        today = time.strftime("%Y-%m-%d")
        self.transactions.setdefault(from_account, []).append(
            {"date": today, "desc": f"Transfer to {to_account}", "amount": -amount})
        self.transactions.setdefault(to_account, []).append(
            {"date": today, "desc": f"Transfer from {from_account}", "amount": amount})
        tid = self._next_id("TRF")
        self.transfers[tid] = {"from": from_account, "to": to_account, "amount": amount,
                               "approval_id": approval_id, "time": time.time()}
        return {"status": "completed", "transfer_id": tid,
                "new_balance": round(src["balance"], 2)}

    # ================================================================ RiskAgent tools
    def check_payee(self, customer_id: str, to_account: str) -> dict[str, Any]:
        cust = self.customers.get(customer_id, {})
        return {"to_account": to_account, "known_payee": to_account in cust.get("payees", []),
                "external": to_account.startswith("EXT-")}

    def daily_transfer_total(self, from_account: str) -> dict[str, Any]:
        cutoff = time.time() - 86400
        total = sum(t["amount"] for t in self.transfers.values()
                    if t["from"] == from_account and t["time"] >= cutoff)
        return {"from_account": from_account, "total_last_24h": round(total, 2)}

    def approve_transfer(self, from_account: str, to_account: str, amount: float) -> dict[str, Any]:
        aid = self._next_id("APR")
        self.approvals[aid] = {"from": from_account, "to": to_account, "amount": amount,
                               "issued_at": time.time(), "used": False}
        return {"approval_id": aid, "valid_for_s": APPROVAL_TTL_SECONDS}

    # ============================================================ shared audit tool
    def record_audit(self, agent: str, event: str, details: dict[str, Any]) -> dict[str, Any]:
        entry = {"seq": len(self.audit_log) + 1, "agent": agent, "event": event, "details": details}
        self.audit_log.append(entry)
        return {"logged": True, "seq": entry["seq"]}
