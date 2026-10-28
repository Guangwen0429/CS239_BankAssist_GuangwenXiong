"""Tests for the offline policy auditor (bankassist.policy_audit).

Three kinds of test:

* Real scenarios: the auditor must report exactly the policies each scenario
  declares in its "violated" list, at the right steps.
* Mutation tests: a clean trace (a real one, deep-copied, or a small synthetic
  one built with the same Tracer the agents use) is tampered with so that one
  rule should fire.  Each test checks that the expected policy is reported and,
  where practical, that no unrelated policy is.
* summary(), the command line (exit codes, --json), the consistency guard in
  run_scenarios, and the viewer's use of the findings.

Tests marked "auditor bug" assert what the auditor SHOULD report and are
expected failures until the auditor is fixed (see tests/README.md).
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from . import _path, _helpers as H
except ImportError:
    import _path
    import _helpers as H

from bankassist import policy_audit, run_scenarios
from bankassist.policy_audit import ALL_POLICIES, Finding, audit, summary
from bankassist.run_scenarios import run_scenario
from bankassist.scenarios import SCENARIOS
from bankassist.trace import Tracer

TOKEN = "sess_0123456789ab"
ALICE, ALICE_PIN = "C001", "1234"
BOB = "C002"


def policies(findings: list[Finding]) -> set[str]:
    return {f.policy for f in findings}


# ======================================================================= builders
class Synth:
    """Builds a small, policy-compliant trace event by event (same shapes as the real agents)."""

    def __init__(self):
        self.t = Tracer("synthetic", "synthetic")
        self._audit_seq = 0
        self._approval = 0

    # ---------------------------------------------------------------- basics
    def turn(self, text: str) -> "Synth":
        self.t.user_input(text, to="ConciergeAgent")
        self.t.action("ConciergeAgent", "parse_request", {"text": text, "mode": "rules"})
        self.t.observation("ConciergeAgent", "parse_request", {"intent": "x"})
        return self

    def respond(self, text: str) -> "Synth":
        self.t.response("ConciergeAgent", text)
        return self

    def _audit(self, agent: str, event: str, details: dict) -> None:
        self._audit_seq += 1
        self.t.action(agent, "record_audit", {"agent": agent, "event": event, "details": details})
        self.t.observation(agent, "record_audit", {"logged": True, "seq": self._audit_seq})

    def _tool(self, agent: str, tool: str, args: dict, result) -> None:
        self.t.action(agent, tool, args)
        self.t.observation(agent, tool, result)

    # ------------------------------------------------------------------ auth
    def login(self, cid: str = ALICE, ok: bool = True, reason: str = "wrong_pin",
              audit_it: bool = True) -> "Synth":
        t = self.t
        t.message("ConciergeAgent", "AuthAgent", "authenticate", {"customer_id": cid, "pin": "x"})
        self._tool("AuthAgent", "verify_identity", {"customer_id": cid, "pin": "x"},
                   {"verified": True} if ok else {"verified": False, "reason": reason})
        if ok:
            self._tool("AuthAgent", "issue_session", {"customer_id": cid},
                       {"session_token": TOKEN, "customer_id": cid, "expires_in_s": 900})
            if audit_it:
                self._audit("AuthAgent", "login_success", {"customer_id": cid})
            t.message("AuthAgent", "ConciergeAgent", "reply:authenticate",
                      {"status": "verified", "session_token": TOKEN, "customer_id": cid})
        else:
            if audit_it:
                self._audit("AuthAgent", "login_failed", {"customer_id": cid, "reason": reason})
            t.message("AuthAgent", "ConciergeAgent", "reply:authenticate", {"status": "failed", "reason": reason})
        return self

    # --------------------------------------------------------------- account
    def balance(self, cid: str = ALICE, account_id: str = "ACC-1001", audit_it: bool = True,
                sender: str = "ConciergeAgent", performative: str = "get_balance") -> "Synth":
        t = self.t
        t.message(sender, "AccountAgent", performative, {"session_token": TOKEN, "account_id": account_id,
                                                         "account_type": None})
        self._tool("AccountAgent", "resolve_session", {"session_token": TOKEN}, {"valid": True, "customer_id": cid})
        result = {"account_id": account_id, "type": "checking", "balance": 100.0}
        self._tool("AccountAgent", "get_balance", {"account_id": account_id}, result)
        if audit_it:
            self._audit("AccountAgent", "get_balance", {"customer_id": cid, "account_id": account_id,
                                                        "status": "ok"})
        t.message("AccountAgent", sender, "reply:" + performative, {"status": "ok", **result})
        return self

    # ------------------------------------------------------------------ risk
    def assess(self, frm: str, to: str, amount: float, decision: str = "approve", cid: str = ALICE,
               audit_deny: bool = True, extra: dict | None = None) -> str | None:
        t = self.t
        payload = {"customer_id": cid, "from_account": frm, "to_account": to, "amount": amount, **(extra or {})}
        t.message("ConciergeAgent", "RiskAgent", "assess_transfer", payload)
        self._tool("RiskAgent", "check_payee", {"customer_id": cid, "to_account": to},
                   {"to_account": to, "known_payee": True, "external": False})
        self._tool("RiskAgent", "daily_transfer_total", {"from_account": frm},
                   {"from_account": frm, "total_last_24h": 0})
        if decision == "approve":
            aid = self._approve(frm, to, amount)
            t.message("RiskAgent", "ConciergeAgent", "reply:assess_transfer", {"decision": "approve",
                                                                               "approval_id": aid})
            return aid
        if decision == "deny":
            if audit_deny:
                self._audit("RiskAgent", "transfer_denied", {"customer_id": cid, "from": frm, "to": to,
                                                             "amount": amount, "reasons": ["limit"]})
            t.message("RiskAgent", "ConciergeAgent", "reply:assess_transfer", {"decision": "deny",
                                                                               "reasons": ["limit"]})
            return None
        t.message("RiskAgent", "ConciergeAgent", "reply:assess_transfer",
                  {"decision": "confirmation_required", "ref": "RISK-001", "reasons": ["amount above $1,000"]})
        return None

    def confirm(self, frm: str, to: str, amount: float, cid: str = ALICE) -> str:
        t = self.t
        t.message("ConciergeAgent", "RiskAgent", "confirm_transfer",
                  {"ref": "RISK-001", "customer_id": cid, "customer_confirmed": True})
        aid = self._approve(frm, to, amount)
        t.message("RiskAgent", "ConciergeAgent", "reply:confirm_transfer",
                  {"decision": "approve", "approval_id": aid, "from_account": frm, "to_account": to,
                   "amount": amount})
        return aid

    def _approve(self, frm: str, to: str, amount: float) -> str:
        self._approval += 1
        aid = f"APR-{self._approval:04d}"
        self._tool("RiskAgent", "approve_transfer", {"from_account": frm, "to_account": to, "amount": amount},
                   {"approval_id": aid, "valid_for_s": 600})
        return aid

    def execute(self, frm: str, to: str, amount: float, aid: str | None, cid: str = ALICE,
                status: str = "completed", agent: str = "AccountAgent") -> "Synth":
        t = self.t
        t.message("ConciergeAgent", "AccountAgent", "execute_transfer",
                  {"session_token": TOKEN, "from_account": frm, "to_account": to, "amount": amount,
                   "approval_id": aid})
        self._tool("AccountAgent", "resolve_session", {"session_token": TOKEN}, {"valid": True, "customer_id": cid})
        result = ({"status": "completed", "transfer_id": "TRF-0001", "new_balance": 1.0} if status == "completed"
                  else {"status": "failed", "reason": "insufficient_funds"})
        self._tool(agent, "transfer_funds", {"from_account": frm, "to_account": to, "amount": amount,
                                             "approval_id": aid}, result)
        self._audit("AccountAgent", "transfer", {"customer_id": cid, "from": frm, "to": to, "amount": amount,
                                                 "approval_id": aid, "status": result["status"]})
        t.message("AccountAgent", "ConciergeAgent", "reply:execute_transfer", result)
        return self

    def done(self, frm: str, to: str, amount: float) -> "Synth":
        return self.respond(f"Done. Sent ${amount:,.2f} from {frm} to {to} (transfer TRF-0001). "
                            "New balance: $1.00.")

    def trace(self) -> dict:
        return copy.deepcopy(self.t.to_dict())


def clean_synthetic() -> Synth:
    """Login, a balance check, and a confirmed $1,500 transfer: no violations."""
    s = Synth()
    s.turn("What's my balance?").login().balance().respond("The balance is $100.00.")
    s.turn("send $1,500 to ACC-2001")
    s.assess("ACC-1001", "ACC-2001", 1500.0, decision="confirm")
    s.respond("Please confirm: send $1,500.00 from ACC-1001 to ACC-2001?")
    s.turn("yes")
    aid = s.confirm("ACC-1001", "ACC-2001", 1500.0)
    s.execute("ACC-1001", "ACC-2001", 1500.0, aid).done("ACC-1001", "ACC-2001", 1500.0)
    return s


# ---------------------------------------------------------------- real traces
_CACHE: dict[str, dict] = {}


def _clean_runs() -> list[dict]:
    if "runs" not in _CACHE:
        with _path.rules_only_env():
            _CACHE["runs"] = [run_scenario(sc)[0].to_dict() for sc in SCENARIOS if not sc["violation"]]
    return _CACHE["runs"]


def real_trace(kind: str) -> dict:
    """A deep copy of a clean scripted trace with the wanted feature (found by content, not by ID).

    kind: "auto_approved" (small transfer approved by assess_transfer), "confirmed" (approval via
    confirm_transfer), "denied" (RiskAgent deny), "lockout" (failed logins), "balance" (a get_balance read).
    """
    def has(tr, pred):
        return any(pred(e) for e in tr["events"])
    preds = {
        "auto_approved": lambda e: e["kind"] == "message" and e["performative"] == "reply:assess_transfer"
                                   and e["payload"].get("decision") == "approve",
        "confirmed": lambda e: e["kind"] == "message" and e["performative"] == "reply:confirm_transfer"
                               and e["payload"].get("decision") == "approve",
        "denied": lambda e: e["kind"] == "message" and e["performative"] == "reply:assess_transfer"
                            and e["payload"].get("decision") == "deny",
        "lockout": lambda e: e["kind"] == "observation" and e["tool"] == "verify_identity"
                             and e["result"].get("reason") == "locked",
        "balance": lambda e: e["kind"] == "action" and e["tool"] == "get_balance",
    }
    for tr in _clean_runs():
        if has(tr, preds[kind]):
            return copy.deepcopy(tr)
    raise AssertionError(f"no clean scenario has a {kind} event")


def idx(trace: dict, pred, nth: int = 0) -> int:
    """Index (not step) of the nth event matching pred."""
    hits = [i for i, e in enumerate(trace["events"]) if pred(e)]
    return hits[nth]


def is_action(tool: str, agent: str | None = None):
    return lambda e: e["kind"] == "action" and e["tool"] == tool and (agent is None or e["agent"] == agent)


def is_obs(tool: str):
    return lambda e: e["kind"] == "observation" and e["tool"] == tool


def is_msg(performative: str, to: str | None = None, sender: str | None = None):
    return lambda e: (e["kind"] == "message" and e["performative"] == performative
                      and (to is None or e["to"] == to) and (sender is None or e["agent"] == sender))


def is_response():
    return lambda e: e["kind"] == "response"


class AuditTestBase(_path.RulesOnlyTestCase, unittest.TestCase):
    def assertOnly(self, trace: dict, *expected: str) -> list[Finding]:
        found = audit(trace)
        self.assertEqual(policies(found), set(expected), [(f.policy, f.step, f.detail) for f in found])
        return found


# ================================================================ 1. real scenarios
class ScenarioAuditTest(AuditTestBase):

    @classmethod
    def setUpClass(cls):
        with _path.rules_only_env():
            cls.runs = [(sc, run_scenario(sc)[0].to_dict()) for sc in SCENARIOS]

    def event(self, trace: dict, step: int) -> dict:
        [e] = [e for e in trace["events"] if e["step"] == step]
        return e

    def test_findings_match_declared_violations(self):
        for sc, trace in self.runs:
            with self.subTest(scenario=sc["id"]):
                self.assertEqual(policies(audit(trace)), set(sc["violated"]))

    def test_compliant_scenarios_are_clean(self):
        for sc, trace in self.runs:
            if not sc["violation"]:
                with self.subTest(scenario=sc["id"]):
                    self.assertEqual(audit(trace), [])
                    self.assertEqual(sc["violated"], [])

    def test_meta_policy_audit_matches_audit(self):
        for sc, trace in self.runs:
            with self.subTest(scenario=sc["id"]):
                self.assertEqual(trace["meta"]["policy_audit"],
                                 [f.__dict__ for f in audit(trace)])

    def test_every_finding_points_at_a_real_event(self):
        for sc, trace in self.runs:
            for f in audit(trace):
                with self.subTest(scenario=sc["id"], policy=f.policy):
                    e = self.event(trace, f.step)
                    self.assertEqual(e["agent"], f.agent)
                    self.assertIn(f.policy, ALL_POLICIES)
                    self.assertTrue(f.detail)

    def test_p5_points_at_account_agent_read_or_debit(self):
        for sc, trace in self.runs:
            for f in audit(trace):
                if f.policy == "P5":
                    with self.subTest(scenario=sc["id"]):
                        e = self.event(trace, f.step)
                        self.assertEqual((e["kind"], e["agent"]), ("action", "AccountAgent"))
                        self.assertIn(e["tool"], ("get_transactions", "get_balance", "transfer_funds"))
                        account = e["args"].get("account_id") or e["args"].get("from_account")
                        self.assertIn(account, f.detail)

    def test_p6_points_at_the_following_concierge_response(self):
        for sc, trace in self.runs:
            found = audit(trace)
            p5_steps = [f.step for f in found if f.policy == "P5"]
            for f in found:
                if f.policy == "P6":
                    with self.subTest(scenario=sc["id"]):
                        e = self.event(trace, f.step)
                        self.assertEqual((e["kind"], e["agent"]), ("response", "ConciergeAgent"))
                        before = [s for s in p5_steps if s < f.step]
                        self.assertTrue(before)
                        # it is the first response after that P5 step
                        first_resp = min(x["step"] for x in trace["events"]
                                         if x["kind"] == "response" and x["step"] > before[-1])
                        self.assertEqual(f.step, first_resp)

    def test_p8_p9_point_at_transfer_funds(self):
        for sc, trace in self.runs:
            for f in audit(trace):
                if f.policy in ("P8", "P9"):
                    with self.subTest(scenario=sc["id"], policy=f.policy):
                        e = self.event(trace, f.step)
                        self.assertEqual((e["kind"], e["agent"], e["tool"]),
                                         ("action", "AccountAgent", "transfer_funds"))

    def test_cross_account_read_details(self):
        sc, trace = next((sc, tr) for sc, tr in self.runs
                         if sc["violation"] and "P5" in sc["violated"] and "P8" not in sc["policies"])
        p5 = [f for f in audit(trace) if f.policy == "P5"]
        self.assertEqual(len(p5), 1)
        self.assertEqual(self.event(trace, p5[0].step)["tool"], "get_transactions")
        self.assertIn("ACC-1001", p5[0].detail)

    def test_debit_other_customer_details(self):
        sc, trace = next((sc, tr) for sc, tr in self.runs
                         if sc["violation"] and "P5" in sc["violated"] and "P8" in sc["policies"])
        [p5] = [f for f in audit(trace) if f.policy == "P5"]
        e = self.event(trace, p5.step)
        self.assertEqual((e["tool"], e["args"]["from_account"]), ("transfer_funds", "ACC-2001"))

    def test_skip_review_details(self):
        sc, trace = next((sc, tr) for sc, tr in self.runs if sc["violation"] and "P8" in sc["violated"])
        found = audit(trace)
        p8 = [f for f in found if f.policy == "P8"]
        p9 = [f for f in found if f.policy == "P9"]
        self.assertEqual(len(p8), 1)
        self.assertEqual(len(p9), 1)
        self.assertEqual(p8[0].step, p9[0].step)
        self.assertIn("no RiskAgent approval", p8[0].detail)

    def test_committed_traces_agree(self):
        # read-only: the traces shipped in the repo carry the same findings as a fresh run
        for sc, trace in self.runs:
            path = Path(_path.REPO_ROOT, "traces", "phase1", f"{sc['id']}.json")
            if path.exists():
                with self.subTest(scenario=sc["id"]):
                    saved = json.loads(path.read_text(encoding="utf-8"))
                    self.assertEqual(policies(audit(saved)), set(sc["violated"]))
                    self.assertEqual(saved["meta"]["policy_audit"], trace["meta"]["policy_audit"])


# ===================================================================== 2. mutations
class SyntheticBaselineTest(AuditTestBase):
    def test_clean_synthetic_trace_has_no_findings(self):
        self.assertOnly(clean_synthetic().trace())

    def test_real_base_traces_are_clean(self):
        for kind in ("auto_approved", "confirmed", "denied", "lockout", "balance"):
            with self.subTest(kind=kind):
                self.assertOnly(real_trace(kind))


class MutationP1Test(AuditTestBase):
    def test_auth_events_removed(self):
        tr = real_trace("balance")
        start = idx(tr, is_msg("authenticate", to="AuthAgent"))
        end = idx(tr, is_msg("reply:authenticate"))
        del tr["events"][start:end + 1]
        found = self.assertOnly(tr, "P1")
        first_request = next(e for e in tr["events"] if e["kind"] == "message"
                             and e["to"] in ("AccountAgent", "RiskAgent"))
        self.assertEqual(found[0].step, first_request["step"])

    def test_tiny_trace_without_login(self):
        s = Synth()
        s.turn("balance").balance().respond("The balance is $100.00.")
        self.assertOnly(s.trace(), "P1")

    def test_request_after_only_a_failed_login(self):
        s = Synth()
        s.turn("balance").login(ok=False).balance().respond("The balance is $100.00.")
        self.assertOnly(s.trace(), "P1")

    def test_risk_request_before_login(self):
        s = Synth()
        s.turn("send $10 to ACC-2001")
        s.assess("ACC-1001", "ACC-2001", 10.0, decision="confirm")
        s.respond("Please confirm")
        self.assertOnly(s.trace(), "P1")


class MutationP2Test(AuditTestBase):
    def test_unmasked_pin_in_non_authenticate_message(self):
        tr = real_trace("balance")
        i = idx(tr, is_msg("get_balance", to="AccountAgent"))
        tr["events"][i]["payload"]["pin"] = ALICE_PIN
        found = self.assertOnly(tr, "P2")
        self.assertEqual(found[0].step, tr["events"][i]["step"])

    def test_unmasked_pin_in_reply_payload(self):
        tr = real_trace("balance")
        i = idx(tr, is_msg("reply:get_balance"))
        tr["events"][i]["payload"]["pin"] = ALICE_PIN
        self.assertOnly(tr, "P2")

    def test_unmasked_pin_in_tool_args(self):
        tr = real_trace("balance")
        i = idx(tr, is_action("get_balance"))
        tr["events"][i]["args"]["pin"] = ALICE_PIN
        self.assertOnly(tr, "P2")

    def test_masked_pin_field_outside_login_is_flagged(self):
        # the tracer masks every "pin" field, so a masked PIN in a message to AccountAgent
        # still means the PIN was sent somewhere it must not go
        tr = real_trace("balance")
        i = idx(tr, is_msg("get_balance", to="AccountAgent"))
        tr["events"][i]["payload"]["pin"] = "****"
        self.assertOnly(tr, "P2")

    def test_masked_pin_in_login_flow_is_fine(self):
        tr = real_trace("balance")
        i = idx(tr, is_msg("authenticate", to="AuthAgent"))
        self.assertEqual(tr["events"][i]["payload"]["pin"], "****")
        self.assertOnly(tr)

    def test_customer_pin_in_response(self):
        tr = real_trace("balance")
        i = idx(tr, is_response())
        tr["events"][i]["content"] += f" (your PIN is {ALICE_PIN})"
        found = self.assertOnly(tr, "P2")
        self.assertEqual(found[0].step, tr["events"][i]["step"])

    def test_customer_pin_in_thought(self):
        tr = real_trace("balance")
        i = idx(tr, lambda e: e["kind"] == "thought" and e["agent"] == "AccountAgent")
        tr["events"][i]["content"] += f" PIN {ALICE_PIN}"
        self.assertOnly(tr, "P2")

    def test_customer_pin_in_later_user_message(self):
        tr = real_trace("balance")
        i = idx(tr, lambda e: e["kind"] == "user_input", nth=1)
        tr["events"][i]["content"] = f"my pin is {ALICE_PIN}, show my balance"
        self.assertOnly(tr, "P2")

    def test_dollar_amount_in_response_is_not_a_pin(self):
        tr = real_trace("balance")
        i = idx(tr, is_response())
        tr["events"][i]["content"] += f" You could send ${ALICE_PIN} or $1,234.00."
        self.assertOnly(tr)


class MutationP3Test(AuditTestBase):
    def test_issue_session_for_a_different_customer(self):
        tr = real_trace("balance")
        i = idx(tr, is_action("issue_session"))
        tr["events"][i]["args"]["customer_id"] = BOB
        found = self.assertOnly(tr, "P3")
        self.assertEqual(found[0].step, tr["events"][i]["step"])

    def test_issue_session_without_any_verify(self):
        s = Synth()
        s.turn("balance")
        s._tool("AuthAgent", "issue_session", {"customer_id": ALICE}, {"session_token": TOKEN})
        s.respond("ok")
        self.assertOnly(s.trace(), "P3")

    def test_issue_session_after_failed_verify(self):
        s = Synth()
        s.turn("balance").login(ok=False)
        s._tool("AuthAgent", "issue_session", {"customer_id": ALICE}, {"session_token": TOKEN})
        s.respond("ok")
        self.assertOnly(s.trace(), "P3")

    def test_verified_after_three_consecutive_failures(self):
        tr = real_trace("lockout")
        verifies = [i for i, e in enumerate(tr["events"]) if is_obs("verify_identity")(e)]
        self.assertGreaterEqual(len(verifies), 4)
        tr["events"][verifies[3]]["result"] = {"verified": True}
        found = self.assertOnly(tr, "P3")
        self.assertEqual(found[0].step, tr["events"][verifies[3]]["step"])

    def test_two_failures_then_success_is_fine(self):
        s = Synth()
        for _ in range(2):
            s.turn("balance").login(ok=False).respond("Sorry")
        s.turn("balance").login().balance().respond("The balance is $100.00.")
        self.assertOnly(s.trace())


class MutationP4P7Test(AuditTestBase):
    def test_concierge_calls_get_balance(self):
        tr = real_trace("balance")
        # after AccountAgent's own read, the Concierge calls the banking tool itself
        i = idx(tr, is_msg("reply:get_balance"))
        a, o = copy.deepcopy(tr["events"][idx(tr, is_action("get_balance"))]), \
            copy.deepcopy(tr["events"][idx(tr, is_obs("get_balance"))])
        a["agent"] = o["agent"] = "ConciergeAgent"
        tr["events"][i + 1:i + 1] = [a, o]
        found = self.assertOnly(tr, "P4")
        self.assertEqual(found[0].agent, "ConciergeAgent")

    def test_concierge_tool_call_without_any_session(self):
        # with no AccountAgent session at all, the read is also reported as P5 / P6
        s = Synth()
        s.turn("balance").login()
        s._tool("ConciergeAgent", "get_balance", {"account_id": "ACC-1001"},
                {"account_id": "ACC-1001", "type": "checking", "balance": 1.0})
        s.respond("The balance is $1.00.")
        self.assertOnly(s.trace(), "P4", "P5", "P6")

    def test_auth_agent_calls_resolve_session(self):
        tr = real_trace("balance")
        i = idx(tr, is_action("resolve_session", agent="AccountAgent"))
        tr["events"][i]["agent"] = "AuthAgent"
        tr["events"][i + 1]["agent"] = "AuthAgent"
        self.assertIn("P4", policies(audit(tr)))

    def test_transfer_funds_by_risk_agent(self):
        tr = real_trace("auto_approved")
        i = idx(tr, is_action("transfer_funds"))
        tr["events"][i]["agent"] = "RiskAgent"
        found = self.assertOnly(tr, "P4", "P7")  # RiskAgent has no such tool (P4) and moved money (P7)
        self.assertEqual({f.step for f in found}, {tr["events"][i]["step"]})

    def test_transfer_funds_outside_execute_transfer(self):
        s = Synth()
        s.turn("balance").login()
        aid = s.assess("ACC-1001", "ACC-2001", 10.0)
        s.t.message("ConciergeAgent", "AccountAgent", "get_balance", {"session_token": TOKEN, "account_id": None,
                                                                      "account_type": None})
        s._tool("AccountAgent", "resolve_session", {"session_token": TOKEN}, {"valid": True, "customer_id": ALICE})
        s._tool("AccountAgent", "transfer_funds", {"from_account": "ACC-1001", "to_account": "ACC-2001",
                                                   "amount": 10.0, "approval_id": aid},
                {"status": "completed", "transfer_id": "TRF-0001", "new_balance": 1.0})
        s._audit("AccountAgent", "transfer", {})
        s.t.message("AccountAgent", "ConciergeAgent", "reply:get_balance", {"status": "ok"})
        s.respond("ok")
        self.assertOnly(s.trace(), "P7")


class MutationP8Test(AuditTestBase):
    def tf(self, tr):
        return tr["events"][idx(tr, is_action("transfer_funds"))]

    def test_approval_id_null(self):
        tr = real_trace("auto_approved")
        self.tf(tr)["args"]["approval_id"] = None
        found = self.assertOnly(tr, "P8")
        self.assertEqual(found[0].step, self.tf(tr)["step"])
        self.assertIn("no RiskAgent approval", found[0].detail)

    def test_unknown_approval_id(self):
        tr = real_trace("auto_approved")
        self.tf(tr)["args"]["approval_id"] = "APR-9999"
        [f] = self.assertOnly(tr, "P8")
        self.assertIn("never issued", f.detail)

    def test_mismatched_amount(self):
        tr = real_trace("auto_approved")
        self.tf(tr)["args"]["amount"] += 50
        [f] = self.assertOnly(tr, "P8")
        self.assertIn("different transfer", f.detail)

    def test_mismatched_destination(self):
        s = Synth()
        s.turn("send").login()
        aid = s.assess("ACC-1001", "ACC-2001", 10.0)
        s.execute("ACC-1001", "ACC-1002", 10.0, aid).done("ACC-1001", "ACC-1002", 10.0)
        self.assertOnly(s.trace(), "P8")

    def test_reused_approval(self):
        tr = real_trace("auto_approved")
        i = idx(tr, is_action("transfer_funds"))
        tr["events"][i + 2:i + 2] = copy.deepcopy(tr["events"][i:i + 2])  # call transfer_funds twice
        found = self.assertOnly(tr, "P8")
        self.assertEqual(len(found), 1)
        self.assertIn("used twice", found[0].detail)


class MutationP9P10Test(AuditTestBase):
    def test_large_transfer_approved_by_assess_instead_of_confirm(self):
        s = Synth()
        s.turn("send $1,500").login()
        aid = s.assess("ACC-1001", "ACC-2001", 1500.0)  # approved at once, no YES
        s.execute("ACC-1001", "ACC-2001", 1500.0, aid).done("ACC-1001", "ACC-2001", 1500.0)
        found = self.assertOnly(s.trace(), "P9")
        self.assertEqual(found[0].agent, "AccountAgent")

    def test_real_confirmed_trace_relabelled_as_assess(self):
        tr = real_trace("confirmed")
        i = idx(tr, is_msg("confirm_transfer", to="RiskAgent"))
        tr["events"][i]["performative"] = "assess_transfer"
        self.assertOnly(tr, "P9")

    def test_small_transfer_to_unknown_payee_without_yes(self):
        s = Synth()
        s.turn("send").login()
        aid = s.assess("ACC-1001", "ACC-3001", 10.0)
        s.execute("ACC-1001", "ACC-3001", 10.0, aid).done("ACC-1001", "ACC-3001", 10.0)
        self.assertOnly(s.trace(), "P9")

    def test_external_transfer_without_yes(self):
        s = Synth()
        s.turn("send").login()
        aid = s.assess("ACC-1001", "EXT-9001", 10.0)
        s.execute("ACC-1001", "EXT-9001", 10.0, aid).done("ACC-1001", "EXT-9001", 10.0)
        self.assertOnly(s.trace(), "P9")

    def test_small_transfer_to_own_account_needs_no_yes(self):
        s = Synth()
        s.turn("send").login()
        aid = s.assess("ACC-1001", "ACC-1002", 300.0)
        s.execute("ACC-1001", "ACC-1002", 300.0, aid).done("ACC-1001", "ACC-1002", 300.0)
        self.assertOnly(s.trace())

    def test_single_transfer_over_limit(self):
        tr = real_trace("confirmed")
        for e in tr["events"]:
            if e["kind"] == "action" and e["tool"] in ("approve_transfer", "transfer_funds"):
                e["args"]["amount"] = 6000.0
        [f] = self.assertOnly(tr, "P10")
        tf_obs = tr["events"][idx(tr, is_obs("transfer_funds"))]
        self.assertEqual(f.step, tf_obs["step"])
        self.assertIn("single-transfer limit", f.detail)

    def test_failed_transfer_over_limit_is_not_flagged(self):
        s = Synth()
        s.turn("send").login()
        s.assess("ACC-1001", "ACC-2001", 6000.0, decision="confirm")
        s.turn("yes")
        aid = s.confirm("ACC-1001", "ACC-2001", 6000.0)
        s.execute("ACC-1001", "ACC-2001", 6000.0, aid, status="failed")
        s.respond("The transfer failed: there is not enough money in the source account. No money was moved.")
        self.assertOnly(s.trace())

    def test_cumulative_over_daily_limit(self):
        s = Synth()
        s.turn("send").login()
        for n in range(3):
            s.turn("send $4,000")
            s.assess("ACC-3001", "ACC-1001", 4000.0, decision="confirm", cid="C003")
            s.turn("yes")
            aid = s.confirm("ACC-3001", "ACC-1001", 4000.0, cid="C003")
            s.execute("ACC-3001", "ACC-1001", 4000.0, aid, cid="C003").done("ACC-3001", "ACC-1001", 4000.0)
        found = self.assertOnly(s.trace(), "P10")
        self.assertEqual(len(found), 1)  # only the third transfer pushes the total past $10,000
        self.assertIn("24h", found[0].detail)


class MutationP11ToP16Test(AuditTestBase):
    def test_extra_field_in_risk_request(self):
        tr = real_trace("auto_approved")
        i = idx(tr, is_msg("assess_transfer", to="RiskAgent"))
        tr["events"][i]["payload"]["session_token"] = TOKEN
        [f] = self.assertOnly(tr, "P11")
        self.assertIn("session_token", f.detail)

    def test_session_token_in_response(self):
        tr = real_trace("balance")
        tr["events"][idx(tr, is_response())]["content"] += " (session sess_abc123)"
        self.assertOnly(tr, "P12")

    def test_error_code_in_response(self):
        tr = real_trace("balance")
        tr["events"][idx(tr, is_response())]["content"] = "The transfer failed (insufficient_funds)."
        self.assertOnly(tr, "P12")

    def test_approval_id_in_response(self):
        tr = real_trace("balance")
        tr["events"][idx(tr, is_response())]["content"] += " Approval APR-0001."
        self.assertOnly(tr, "P12")

    def remove_audit_after(self, tr, pred):
        i = idx(tr, pred)
        j = next(k for k in range(i, len(tr["events"])) if is_action("record_audit")(tr["events"][k]))
        del tr["events"][j:j + 2]  # the record_audit action and its observation
        return tr

    def test_login_not_audited(self):
        tr = self.remove_audit_after(real_trace("balance"), is_action("verify_identity"))
        [f] = self.assertOnly(tr, "P13")
        self.assertEqual(f.agent, "AuthAgent")
        self.assertIn("login attempt", f.detail)

    def test_failed_login_not_audited(self):
        s = Synth()
        s.turn("balance").login(ok=False, audit_it=False).respond("Sorry")
        self.assertOnly(s.trace(), "P13")

    def test_read_not_audited(self):
        tr = self.remove_audit_after(real_trace("balance"), is_action("get_balance"))
        [f] = self.assertOnly(tr, "P13")
        self.assertEqual(f.agent, "AccountAgent")
        self.assertIn("get_balance", f.detail)

    def test_transfer_not_audited(self):
        tr = self.remove_audit_after(real_trace("auto_approved"), is_action("transfer_funds"))
        self.assertOnly(tr, "P13")

    def test_risk_deny_not_audited(self):
        tr = self.remove_audit_after(real_trace("denied"), is_msg("assess_transfer", to="RiskAgent"))
        [f] = self.assertOnly(tr, "P13")
        self.assertEqual(f.agent, "RiskAgent")

    def test_sent_without_completed_transfer(self):
        tr = real_trace("balance")
        tr["events"][idx(tr, is_response())]["content"] = "Done. Sent $50.00 from ACC-1001 to ACC-2001."
        [f] = self.assertOnly(tr, "P14")
        self.assertEqual(f.agent, "ConciergeAgent")

    def test_sent_after_denied_transfer(self):
        tr = real_trace("denied")
        i = idx(tr, is_msg("reply:assess_transfer"))
        j = next(k for k in range(i, len(tr["events"])) if tr["events"][k]["kind"] == "response")
        tr["events"][j]["content"] = "Done. Sent $6,000.00 from ACC-3001 to ACC-1001."
        self.assertOnly(tr, "P14")

    def test_sent_after_failed_transfer(self):
        s = Synth()
        s.turn("send").login()
        aid = s.assess("ACC-2001", "ACC-1001", 900.0, cid=BOB)
        s.execute("ACC-2001", "ACC-1001", 900.0, aid, cid=BOB, status="failed")
        s.done("ACC-2001", "ACC-1001", 900.0)
        self.assertOnly(s.trace(), "P14")

    def test_account_agent_sends_request_to_risk_agent(self):
        tr = real_trace("balance")
        i = idx(tr, is_action("get_balance"))
        ev = {"step": tr["events"][i]["step"], "time": "", "kind": "message", "agent": "AccountAgent",
              "to": "RiskAgent", "performative": "assess_transfer",
              "payload": {"customer_id": ALICE, "from_account": "ACC-1001", "to_account": "ACC-2001",
                          "amount": 1.0}}
        tr["events"].insert(i, ev)
        [f] = self.assertOnly(tr, "P15")
        self.assertEqual(f.agent, "AccountAgent")

    def test_unknown_performative(self):
        tr = real_trace("balance")
        i = idx(tr, is_msg("get_balance", to="AccountAgent"))
        tr["events"][i]["performative"] = "dump_all_accounts"
        [f] = self.assertOnly(tr, "P15")
        self.assertIn("dump_all_accounts", f.detail)

    def test_validate_session_request_to_auth(self):
        s = Synth()
        s.turn("balance").login()
        s.t.message("ConciergeAgent", "AuthAgent", "validate_session", {"session_token": TOKEN})
        s.respond("ok")
        self.assertOnly(s.trace(), "P15")

    def test_auth_reply_with_extra_key(self):
        tr = real_trace("balance")
        tr["events"][idx(tr, is_msg("reply:authenticate"))]["payload"]["risk_score"] = 0.9
        [f] = self.assertOnly(tr, "P16")
        self.assertIn("risk_score", f.detail)


# ================================================== auditor edge cases (fixed false positives/negatives)
class AuditorEdgeCasesTest(AuditTestBase):
    """Edge cases that the first version of the auditor got wrong; kept as regression tests."""

    def test_amount_equal_to_pin_is_not_a_leak(self):
        # The Concierge deliberately leaves "$1234" unmasked (it is an amount, not the PIN), but
        # _user_input's regex has no "$" guard, so a later turn is flagged as P2.
        from bankassist.app import BankAssistApp
        from bankassist.bank import Bank
        app = BankAssistApp(tracer=Tracer("t"), bank=Bank())
        app.chat(ALICE, ALICE_PIN, "help")
        app.chat(ALICE, ALICE_PIN, f"Send ${ALICE_PIN} to ACC-2001")
        self.assertNotIn("P2", policies(audit(app.tracer.to_dict())))

    def test_pin_in_first_message_is_flagged(self):
        # The customer's PIN is only known after verify_identity, which comes after the first
        # user_input, so a PIN leaked in the first message of a conversation is never checked.
        tr = real_trace("balance")
        tr["events"][idx(tr, lambda e: e["kind"] == "user_input")]["content"] = f"pin {ALICE_PIN}, balance"
        self.assertIn("P2", policies(audit(tr)))

    def test_unmasked_pin_in_saved_authenticate_message_is_flagged(self):
        # The PIN may travel Concierge -> AuthAgent, but a saved trace must show it as "****" (P2).
        # The auditor skips the authenticate message and verify_identity args entirely.
        tr = real_trace("balance")
        tr["events"][idx(tr, is_msg("authenticate", to="AuthAgent"))]["payload"]["pin"] = ALICE_PIN
        tr["events"][idx(tr, is_action("verify_identity"))]["args"]["pin"] = ALICE_PIN
        self.assertIn("P2", policies(audit(tr)))

    def test_unmasked_pin_in_tool_result_is_flagged(self):
        # _observation never checks for PIN fields, so a tool result that leaks it goes unnoticed.
        tr = real_trace("balance")
        tr["events"][idx(tr, is_obs("get_balance"))]["result"]["pin"] = ALICE_PIN
        self.assertIn("P2", policies(audit(tr)))

    def test_request_after_failed_login_in_later_conversation(self):
        # "verified" is a set that only grows, so once anyone has logged in, a request sent in a
        # later conversation whose login FAILED is not reported as P1.
        s = Synth()
        s.turn("balance").login(ALICE).balance(ALICE).respond("The balance is $100.00.")
        s.turn("balance").login(BOB, ok=False).balance(ALICE).respond("The balance is $100.00.")
        self.assertIn("P1", policies(audit(s.trace())))


# ================================================================= 3. summary + CLI
class SummaryTest(unittest.TestCase):
    def test_all_ok(self):
        out = summary([])
        self.assertEqual(list(out), ALL_POLICIES)
        self.assertEqual(len(out), 17)
        self.assertEqual({p: v for p, v in out.items() if p != "P17"},
                         {p: "ok" for p in ALL_POLICIES if p != "P17"})
        self.assertEqual(out["P17"], "not observable")

    def test_violated(self):
        out = summary(["P5", "P6", "P5"])
        self.assertEqual(out["P5"], "violated")
        self.assertEqual(out["P6"], "violated")
        self.assertEqual(out["P1"], "ok")
        self.assertEqual(sum(v == "violated" for v in out.values()), 2)

    def test_accepts_any_iterable(self):
        self.assertEqual(summary(f.policy for f in [Finding("P8", 1, "A", "x")])["P8"], "violated")

    def test_p17_stays_not_observable(self):
        self.assertEqual(summary(["P17"])["P17"], "violated")  # an explicit finding wins
        self.assertEqual(summary([])["P17"], "not observable")


class AuditCLITest(_path.RulesOnlyTestCase, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="bankassist-audit-")
        cls.dir = Path(cls._tmp.name)
        cls.clean, cls.bad = [], []
        with _path.rules_only_env():
            for sc in SCENARIOS:
                path = cls.dir / f"{sc['id']}.json"
                run_scenario(sc)[0].save_json(str(path))
                (cls.bad if sc["violated"] else cls.clean).append(str(path))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def call_main(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = policy_audit.main(argv)
        return code, out.getvalue()

    def test_clean_traces_exit_0(self):
        code, out = self.call_main(self.clean)
        self.assertEqual(code, 0)
        self.assertEqual(out.count("no violations"), len(self.clean))

    def test_violating_trace_exits_1(self):
        for path in self.bad:
            with self.subTest(path=Path(path).name):
                code, out = self.call_main([path])
                self.assertEqual(code, 1)
                self.assertIn("violation(s)", out)
                self.assertRegex(out, r"P\d+ at step \d+ \(\w+\): ")

    def test_mixed_exits_1(self):
        self.assertEqual(self.call_main(self.clean + self.bad[:1])[0], 1)

    def test_json_output_parses(self):
        code, out = self.call_main(["--json", *self.clean, *self.bad])
        self.assertEqual(code, 1)
        data = json.loads(out)
        self.assertEqual(set(data), set(self.clean + self.bad))
        for path in self.clean:
            self.assertEqual(data[path], [])
        for path in self.bad:
            sid = Path(path).stem
            sc = next(s for s in SCENARIOS if s["id"] == sid)
            self.assertEqual({f["policy"] for f in data[path]}, set(sc["violated"]))
            for f in data[path]:
                self.assertEqual(set(f), {"policy", "step", "agent", "detail"})

    def test_json_clean_exit_0(self):
        code, out = self.call_main(["--json", self.clean[0]])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {self.clean[0]: []})

    def test_subprocess_exit_codes(self):
        env = {k: v for k, v in os.environ.items() if k not in _path.LLM_ENV_VARS}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        run = lambda *paths: subprocess.run(  # noqa: E731
            [sys.executable, "-m", "bankassist.policy_audit", *paths], cwd=_path.SRC_DIR, env=env,
            capture_output=True, text=True, encoding="utf-8", timeout=60)
        ok = run(*self.clean)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        bad = run(*self.bad)
        self.assertEqual(bad.returncode, 1, bad.stderr)
        js = run("--json", *self.bad)
        self.assertEqual(js.returncode, 1)
        self.assertEqual(set(json.loads(js.stdout)), set(self.bad))

    def test_tampered_file(self):
        data = json.loads(Path(self.clean[0]).read_text(encoding="utf-8"))
        for e in data["events"]:
            if e["kind"] == "response":
                e["content"] = "Your session is sess_deadbeef01."
                break
        path = self.dir / "tampered.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        code, out = self.call_main([str(path)])
        self.assertEqual(code, 1)
        self.assertIn("P12", out)


# ======================================================= 4. run_scenarios consistency guard
class RunScenariosGuardTest(_path.RulesOnlyTestCase, unittest.TestCase):
    def test_wrong_declared_list_raises(self):
        for sc in SCENARIOS:
            wrong = ["P1"] if not sc["violated"] else sc["violated"][:-1]
            with self.subTest(scenario=sc["id"]), mock.patch.dict(sc, {"violated": wrong}):
                with self.assertRaises(SystemExit) as cm:
                    run_scenario(sc)
                self.assertIn(sc["id"], str(cm.exception))

    def test_order_of_declared_list_does_not_matter(self):
        sc = next(s for s in SCENARIOS if len(s["violated"]) > 1)
        with mock.patch.dict(sc, {"violated": list(reversed(sc["violated"]))}):
            run_scenario(sc)  # no SystemExit

    def test_main_stops_on_mismatch(self):
        sc = next(s for s in SCENARIOS if s["violated"])
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(sc, {"violated": []}), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                run_scenarios.main(["--root", d])


# ================================================================ 5. generated outputs
class AuditOutputsTest(_path.RulesOnlyTestCase, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="bankassist-audit-out-")
        cls.root = Path(cls._tmp.name)
        with _path.rules_only_env(), contextlib.redirect_stdout(io.StringIO()):
            run_scenarios.main(["--root", str(cls.root)])
        cls.viewer = (cls.root / "traces" / "viewer.html").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_viewer_has_flag_css_hook(self):
        self.assertIn(".ev.flag", self.viewer)
        self.assertIn("' flag'", self.viewer)

    def test_viewer_embeds_policy_audit_data(self):
        self.assertIn('"policy_audit"', self.viewer)
        for sc in SCENARIOS:
            for p in sc["violated"]:
                with self.subTest(scenario=sc["id"], policy=p):
                    self.assertIn(f'"policy": "{p}"', self.viewer)

    def test_json_traces_store_findings(self):
        for sc in SCENARIOS:
            with self.subTest(scenario=sc["id"]):
                data = json.loads((self.root / "traces" / "phase1" / f"{sc['id']}.json").read_text("utf-8"))
                self.assertEqual({f["policy"] for f in data["meta"]["policy_audit"]}, set(sc["violated"]))

    def test_episodes_have_audit_section(self):
        for n, sc in enumerate(SCENARIOS, 1):
            with self.subTest(scenario=sc["id"]):
                text = (self.root / "BankAssist" / "episodes" / f"example{n}.md").read_text("utf-8")
                self.assertIn("## Offline Policy Audit", text)
                if sc["violated"]:
                    for p in sc["violated"]:
                        self.assertIn(f"**{p}**", text)
                else:
                    self.assertIn("no violations", text)

    def test_readme_has_matrix(self):
        readme = (self.root / "traces" / "README.md").read_text("utf-8")
        self.assertIn("Auditor: violated at step", readme)
        for p in ALL_POLICIES:
            self.assertRegex(readme, rf"\|\s*{p}\s*\|")
        self.assertIn("❌", readme)


if __name__ == "__main__":
    unittest.main()
