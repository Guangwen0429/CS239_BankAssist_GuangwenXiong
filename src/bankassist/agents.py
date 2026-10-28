"""The four BankAssist agents and the message bus that connects them.

    User ──► ConciergeAgent ──► AuthAgent      (identity, sessions)
                    │
                    ├─────────► RiskAgent      (transfer review / approval)
                    │
                    └─────────► AccountAgent   (balances, history, money movement)

Agents never call each other's methods directly: every request goes through
`MessageBus.send`, which records the request and the reply in the trace.

PHASE 1 NOTE.  This is the prototype *without* a safety-enforcing framework.
The agents follow the happy path of policy.md, but several checks are
missing on purpose (they will be enforced in Phase 2).  Each gap is marked
with a "PHASE-1 GAP" comment and the policy it breaks.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

import time

from .bank import (APPROVAL_TTL_SECONDS, DAILY_TRANSFER_LIMIT, SINGLE_TRANSFER_LIMIT,
                   STEP_UP_THRESHOLD, Bank)
from .llm import LLMUnavailable, chat, llm_config
from .trace import Tracer


# =========================================================================== bus
class MessageBus:
    def __init__(self, tracer: Tracer):
        self.tracer = tracer
        self.agents: dict[str, "Agent"] = {}

    def register(self, agent: "Agent") -> None:
        self.agents[agent.name] = agent

    def send(self, sender: str, recipient: str, performative: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.tracer.message(sender, recipient, performative, payload)
        reply = self.agents[recipient].handle(sender, performative, payload)
        self.tracer.message(recipient, sender, "reply:" + performative, reply)
        return reply


class Agent:
    name = "Agent"

    def __init__(self, bus: MessageBus, bank: Bank, tracer: Tracer):
        self.bus, self.bank, self.tracer = bus, bank, tracer
        bus.register(self)

    def think(self, text: str) -> None:
        self.tracer.thought(self.name, text)

    def call_tool(self, tool: str, **args: Any) -> Any:
        self.tracer.action(self.name, tool, args)
        result = getattr(self.bank, tool)(**args)
        self.tracer.observation(self.name, tool, result)
        return result

    def send(self, recipient: str, performative: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.bus.send(self.name, recipient, performative, payload)

    def handle(self, sender: str, performative: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


# ===================================================================== AuthAgent
class AuthAgent(Agent):
    """Rule-based.  Verifies customer ID + PIN and issues session tokens."""

    name = "AuthAgent"

    def handle(self, sender, performative, payload):
        if performative == "authenticate":
            cid = str(payload.get("customer_id", "")).strip().upper()
            self.think(f"Verifying identity for customer {cid}.")
            res = self.call_tool("verify_identity", customer_id=cid, pin=payload.get("pin", ""))
            if res["verified"]:
                sess = self.call_tool("issue_session", customer_id=cid)
                self.call_tool("record_audit", agent=self.name, event="login_success",
                               details={"customer_id": cid})
                self.think("PIN correct; session issued.")
                return {"status": "verified", "session_token": sess["session_token"], "customer_id": cid}
            self.call_tool("record_audit", agent=self.name, event="login_failed",
                           details={"customer_id": cid, "reason": res["reason"]})
            self.think(f"Verification failed ({res['reason']}).")
            out = {"status": "failed", "reason": res["reason"]}
            if "attempts_left" in res:
                out["attempts_left"] = res["attempts_left"]
            return out

        return {"status": "error", "reason": f"unsupported request {performative}"}


# ================================================================== AccountAgent
class AccountAgent(Agent):
    """Rule-based.  The only agent that reads account data or moves money."""

    name = "AccountAgent"

    def _customer_for(self, session_token: str) -> str | None:
        res = self.call_tool("resolve_session", session_token=session_token)
        return res["customer_id"] if res.get("valid") else None

    def _pick_account(self, customer_id: str, account_type: str | None) -> str | None:
        accts = self.call_tool("list_accounts", customer_id=customer_id)["accounts"]
        wanted = account_type or "checking"
        for a in accts:
            if a["type"] == wanted:
                return a["account_id"]
        if account_type is None and accts:
            return accts[0]["account_id"]
        return None

    def handle(self, sender, performative, payload):
        cid = self._customer_for(payload.get("session_token", ""))
        if cid is None:
            self.think("Session token is missing or invalid; refusing.")
            return {"status": "error", "reason": "invalid_session"}

        if performative == "list_my_accounts":
            return {"status": "ok", **self.call_tool("list_accounts", customer_id=cid)}

        if performative in ("get_balance", "get_transactions"):
            account_id = payload.get("account_id")
            if account_id:
                # PHASE-1 GAP (breaks P5): the account named in the request is used
                # as-is; we never check that it belongs to the session's customer.
                self.think(f"Request names account {account_id}; using it.")
            else:
                account_id = self._pick_account(cid, payload.get("account_type"))
                if account_id is None:
                    self.think(f"Customer {cid} has no {payload.get('account_type')} account.")
                    return {"status": "error", "reason": "no_account_of_type"}
                self.think(f"No account named; using customer {cid}'s "
                           f"{payload.get('account_type') or 'checking'} account {account_id}.")
            if performative == "get_balance":
                res = self.call_tool("get_balance", account_id=account_id)
            else:
                res = self.call_tool("get_transactions", account_id=account_id, limit=5)
            self.call_tool("record_audit", agent=self.name, event=performative,
                           details={"customer_id": cid, "account_id": account_id,
                                    "status": "error" if "error" in res else "ok"})
            if "error" in res:
                return {"status": "error", "reason": res["error"]}
            return {"status": "ok", **res}

        if performative == "execute_transfer":
            frm, to, amt = payload["from_account"], payload["to_account"], float(payload["amount"])
            approval_id = payload.get("approval_id")
            # PHASE-1 GAP (breaks P8): approval_id is passed through but never
            # validated; a transfer with no approval at all is still executed.
            self.think(f"Executing transfer of ${amt:,.2f} {frm} -> {to} "
                       f"(approval_id={approval_id}).")
            res = self.call_tool("transfer_funds", from_account=frm, to_account=to,
                                 amount=amt, approval_id=approval_id)
            self.call_tool("record_audit", agent=self.name, event="transfer",
                           details={"customer_id": cid, "from": frm, "to": to, "amount": amt,
                                    "approval_id": approval_id, "status": res["status"]})
            return res

        return {"status": "error", "reason": f"unsupported request {performative}"}


# ===================================================================== RiskAgent
class RiskAgent(Agent):
    """Rule-based fraud / limit checks.  Issues approvals for transfers."""

    name = "RiskAgent"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.pending: dict[str, dict] = {}
        self._ref_counter = 0

    def handle(self, sender, performative, payload):
        if performative == "assess_transfer":
            cid, frm, to = payload["customer_id"], payload["from_account"], payload["to_account"]
            amt = float(payload["amount"])
            payee = self.call_tool("check_payee", customer_id=cid, to_account=to)
            daily = self.call_tool("daily_transfer_total", from_account=frm)
            reasons_deny, reasons_step = [], []
            if amt > SINGLE_TRANSFER_LIMIT:
                reasons_deny.append(f"amount exceeds single-transfer limit ${SINGLE_TRANSFER_LIMIT:,.0f}")
            if daily["total_last_24h"] + amt > DAILY_TRANSFER_LIMIT:
                reasons_deny.append(f"would exceed 24h limit ${DAILY_TRANSFER_LIMIT:,.0f}")
            if amt > STEP_UP_THRESHOLD:
                reasons_step.append(f"amount above ${STEP_UP_THRESHOLD:,.0f}")
            if not payee["known_payee"]:
                reasons_step.append("payee not in customer's saved payees")
            if payee["external"]:
                reasons_step.append("external (other-bank) account")

            if reasons_deny:
                self.think("Hard limit hit: " + "; ".join(reasons_deny) + ". Denying.")
                self.call_tool("record_audit", agent=self.name, event="transfer_denied",
                               details={"customer_id": cid, "from": frm, "to": to, "amount": amt,
                                        "reasons": reasons_deny})
                return {"decision": "deny", "reasons": reasons_deny}
            if reasons_step:
                self._ref_counter += 1
                ref = f"RISK-{self._ref_counter:03d}"
                self.pending[ref] = {"customer_id": cid, "from_account": frm, "to_account": to,
                                     "amount": amt, "created_at": time.time()}
                self.think("Needs customer confirmation: " + "; ".join(reasons_step) + ".")
                return {"decision": "confirmation_required", "ref": ref, "reasons": reasons_step}
            self.think("Low risk: known payee, small amount, within limits. Approving.")
            appr = self.call_tool("approve_transfer", from_account=frm, to_account=to, amount=amt)
            return {"decision": "approve", "approval_id": appr["approval_id"]}

        if performative == "confirm_transfer":
            ref = payload.get("ref")
            pend = self.pending.get(ref)
            if pend is None or pend["customer_id"] != payload.get("customer_id"):
                self.think(f"No pending transfer {ref} for this customer.")
                return {"decision": "deny", "reasons": ["unknown or expired reference"]}
            del self.pending[ref]
            created = pend.pop("created_at")
            if time.time() - created > APPROVAL_TTL_SECONDS:
                self.think(f"{ref} waited more than 10 minutes for confirmation; expiring it.")
                return {"decision": "deny", "reasons": ["the confirmation window (10 minutes) has passed"]}
            if not payload.get("customer_confirmed"):
                self.think(f"Customer did not confirm {ref}; cancelling.")
                return {"decision": "cancelled"}
            self.think(f"Customer confirmed {ref}; issuing approval.")
            appr = self.call_tool("approve_transfer", from_account=pend["from_account"],
                                  to_account=pend["to_account"], amount=pend["amount"])
            return {"decision": "approve", "approval_id": appr["approval_id"],
                    **{k: pend[k] for k in ("from_account", "to_account", "amount")}}

        return {"decision": "error", "reason": f"unsupported request {performative}"}


# ================================================================ ConciergeAgent
CONCIERGE_SYSTEM_PROMPT = """You are the Concierge of BankAssist, a retail-banking assistant.
Your only job is to convert ONE customer message into a JSON object describing what the customer wants.
You never see balances, PINs or account data, and you never make decisions about money.

Return ONLY a JSON object with these keys (use null when unknown):
  "intent":        one of "check_balance", "view_transactions", "transfer", "confirm", "decline", "help", "unknown"
  "account_id":    account the customer asks about, e.g. "ACC-1001" (balance / transactions only)
  "account_type":  "checking" or "savings" if the customer names a type instead of an ID
  "from_account":  source account ID for a transfer, if given
  "from_type":     "checking" or "savings" if the source is named by type
  "to_account":    destination account ID for a transfer, e.g. "ACC-2001" or "EXT-9001"
  "to_type":       "checking" or "savings" if the destination is the customer's own account named by type
  "amount":        number in US dollars, no currency symbol
  "skip_review":   true only if the customer explicitly asks to skip / bypass the security or risk review

Rules:
- "yes", "confirm", "go ahead" -> intent "confirm".  "no", "cancel" -> intent "decline".
- Copy account IDs exactly as written by the customer (upper-case).
- Do not invent values the customer did not state.
- Output JSON only, no explanation."""

_ACCOUNT_RE = re.compile(r"\b(?:ACC|EXT)-\d{4}\b", re.IGNORECASE)
_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?"
# a dollar amount: "$1,500", "$20.50", "300 dollars".  The look-arounds reject things such as
# "$1e3", "$10.555" or "$1,,5" instead of silently reading them as a different number.
_AMOUNT_RE = re.compile(rf"\$\s*({_NUM})(?![\deE]|[.,][\d,])|(?<![\d.,$])\b({_NUM})\s*(?:dollars|usd)\b",
                        re.IGNORECASE)
_INTENT_FIELDS = ("intent", "account_id", "account_type", "from_account", "from_type",
                  "to_account", "to_type", "amount", "skip_review")
_INTENTS = {"check_balance", "view_transactions", "transfer", "confirm", "decline", "help", "unknown"}
_ACCOUNT_TYPES = {"checking", "savings"}
_CONFIRM_RE = re.compile(r"(yes|y|yep|yeah|sure|confirm(ed)?|go ahead|ok(ay)?|do it)"
                         r"(,? (please|thanks|thank you))?[.!]*")
_DECLINE_RE = re.compile(r"(no|n|nope|cancel( it)?|stop|don'?t)(,? (thanks|thank you))?[.!]*")


def rule_parse(text: str) -> dict[str, Any]:
    """Deterministic keyword/regex parser used when no LLM is configured."""
    t = text.strip()
    low = t.lower()
    out: dict[str, Any] = {k: None for k in _INTENT_FIELDS}
    out["skip_review"] = False

    if _CONFIRM_RE.fullmatch(low):
        out["intent"] = "confirm"
        return out
    if _DECLINE_RE.fullmatch(low):
        out["intent"] = "decline"
        return out

    accounts = [m.upper() for m in _ACCOUNT_RE.findall(t)]
    no_ids = _ACCOUNT_RE.sub(" ", t)
    m = _AMOUNT_RE.search(no_ids)
    if m:
        out["amount"] = float((m.group(1) or m.group(2)).replace(",", ""))

    if re.search(r"\b(transfer|send|wire|pay|move)\b", low):
        out["intent"] = "transfer"
        fm = re.search(r"\bfrom\s+(?:my\s+)?((?:acc|ext)-\d{4}|checking|savings)\b", low)
        tm = re.search(r"\bto\s+(?:my\s+|account\s+)?((?:acc|ext)-\d{4}|checking|savings)\b", low)
        if fm:
            v = fm.group(1)
            out["from_account" if "-" in v else "from_type"] = v.upper() if "-" in v else v
        destinations = {a for a in accounts if a != out["from_account"]}
        if len(destinations) > 1:
            pass  # several possible destinations: leave it unset so the customer is asked
        elif tm and "-" in tm.group(1):
            out["to_account"] = tm.group(1).upper()
        elif tm:
            out["to_type"] = tm.group(1)
        elif destinations:
            out["to_account"] = destinations.pop()
        out["skip_review"] = bool(re.search(
            r"\b(skip|bypass|without (the )?(security|risk|review|check|verification)\b|no (need for|review|check)\b)",
            low))
        if re.search(r"\b(cancel|never ?mind|actually no|don'?t send)\b", low):
            out["intent"] = "decline"  # the customer took the request back in the same message
    elif re.search(r"\b(transactions?|history|statement|activity|spent|purchases)\b", low):
        out["intent"] = "view_transactions"
    elif re.search(r"\b(balance|how much)\b", low):
        out["intent"] = "check_balance"
    elif re.search(r"\b(help|what can you do)\b", low):
        out["intent"] = "help"
    else:
        out["intent"] = "unknown"

    if out["intent"] in ("check_balance", "view_transactions"):
        out["account_id"] = accounts[0] if accounts else None
        for kind in ("savings", "checking"):
            if kind in low:
                out["account_type"] = kind
    return out


def normalize_request(cand: Any) -> dict[str, Any] | None:
    """Validate an LLM answer and coerce it to the same shape as rule_parse(); None if unusable."""
    if not isinstance(cand, dict) or not isinstance(cand.get("intent"), str) or cand["intent"] not in _INTENTS:
        return None
    out: dict[str, Any] = {k: None for k in _INTENT_FIELDS}
    out["intent"] = cand["intent"]
    for key in ("account_id", "from_account", "to_account"):
        v = cand.get(key)
        if isinstance(v, str) and _ACCOUNT_RE.fullmatch(v.strip()):
            out[key] = v.strip().upper()
    for key in ("account_type", "from_type", "to_type"):
        v = cand.get(key)
        if isinstance(v, str) and v.strip().lower() in _ACCOUNT_TYPES:
            out[key] = v.strip().lower()
    amt = cand.get("amount")
    if isinstance(amt, str):
        try:
            amt = float(amt.replace("$", "").replace(",", "").strip())
        except ValueError:
            amt = None
    if isinstance(amt, (int, float)) and not isinstance(amt, bool) and math.isfinite(amt) and amt > 0:
        out["amount"] = float(amt)
    sr = cand.get("skip_review")
    out["skip_review"] = sr is True or (isinstance(sr, str) and sr.strip().lower() == "true")
    return out


_REASONS = {
    "no_such_account": "that account does not exist",
    "no_account_of_type": "there is no account of that type on your profile",
    "insufficient_funds": "there is not enough money in the source account",
    "invalid_amount": "the amount is not valid",
    "invalid_session": "your session could not be verified",
}


def _explain(reason: Any) -> str:
    """Customer-facing wording for an internal error code (P12)."""
    return _REASONS.get(reason, "something went wrong on our side")


def _money(x: float) -> str:
    return f"-${-x:,.2f}" if x < 0 else f"${x:,.2f}"


class ConciergeAgent(Agent):
    """Customer-facing entry point.  Understands requests (rules or LLM) and routes them.

    It holds no banking tools: it can only talk to the other agents.
    """

    name = "ConciergeAgent"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.session_token: str | None = None
        self.customer_id: str | None = None
        self.pending_ref: str | None = None
        self._creds: tuple[str, str] | None = None  # only set while a customer turn is running

    # ------------------------------------------------------------ understanding
    def parse_request(self, text: str) -> dict[str, Any]:
        mode = "llm" if llm_config() else "rules"
        self.tracer.action(self.name, "parse_request", {"text": text, "mode": mode})
        parsed = None
        if mode == "llm":
            try:
                raw = chat(CONCIERGE_SYSTEM_PROMPT, text)
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                parsed = normalize_request(json.loads(m.group(0)) if m else None)
                if parsed is None:
                    self.think("LLM answer was not a usable request; falling back to rule parser.")
            except (LLMUnavailable, ValueError, TypeError) as exc:
                self.think(f"LLM unavailable ({exc}); falling back to rule parser.")
        if parsed is None:
            parsed = rule_parse(text)
        self.tracer.observation(self.name, "parse_request", parsed)
        return parsed

    # --------------------------------------------------------------- one turn
    def handle_user(self, customer_id: str, pin: str, text: str) -> str:
        if pin and len(pin) >= 4:
            # a PIN typed into the chat text is masked before it is traced or parsed (P2)
            text = re.sub(rf"(?<![\d$.,]){re.escape(pin)}(?![\d.,])", "****", text)
        self.tracer.user_input(text, to=self.name)
        self._creds = (customer_id, pin)
        try:
            reply = self._turn(customer_id, pin, text)
        finally:
            self._creds = None
        self.tracer.response(self.name, reply)
        return reply

    def _authenticate(self, customer_id: str, pin: str) -> str | None:
        """Log the customer in through AuthAgent.  Returns an error reply, or None on success."""
        auth = self.send("AuthAgent", "authenticate", {"customer_id": customer_id, "pin": pin})
        if auth["status"] != "verified":
            self.session_token = self.customer_id = None
            if auth.get("reason") == "locked":
                return ("For your security this profile is locked after too many failed PIN "
                        "attempts. Please call 1-800-555-0100 to unlock it.")
            left = auth.get("attempts_left")
            return ("Sorry, I couldn't verify your identity, so I can't help with account requests."
                    + (f" {left} attempt(s) left before the profile is locked." if left else ""))
        self.session_token, self.customer_id = auth["session_token"], auth["customer_id"]
        return None

    def _ask_account(self, performative: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Send a request to AccountAgent; if the session expired, log in again once and retry."""
        res = self.send("AccountAgent", performative, {"session_token": self.session_token, **payload})
        if res.get("reason") == "invalid_session" and self._creds:
            self.think("Session expired; asking AuthAgent to verify the customer again.")
            if self._authenticate(*self._creds) is None:
                res = self.send("AccountAgent", performative, {"session_token": self.session_token, **payload})
        return res

    def _turn(self, customer_id: str, pin: str, text: str) -> str:
        if self.session_token is None:
            self.think("No active session; asking AuthAgent to verify the customer first.")
            error = self._authenticate(customer_id, pin)
            if error:
                return error

        req = self.parse_request(text)
        intent = req["intent"]

        if intent in ("confirm", "decline"):
            return self._finish_pending(confirmed=(intent == "confirm"))
        notice = ""
        if self.pending_ref:
            ref = self.pending_ref
            self.think(f"New request while {ref} is waiting; cancelling the pending transfer.")
            self.cancel_pending()
            notice = "(Your transfer that was waiting for confirmation has been cancelled; no money was moved.) "
        return notice + self._route(req)

    def cancel_pending(self) -> None:
        """Tell RiskAgent to drop a transfer that is still waiting for the customer's YES."""
        if self.pending_ref:
            ref, self.pending_ref = self.pending_ref, None
            self.send("RiskAgent", "confirm_transfer",
                      {"ref": ref, "customer_id": self.customer_id, "customer_confirmed": False})

    def _route(self, req: dict[str, Any]) -> str:
        intent = req["intent"]

        if intent == "check_balance":
            res = self._ask_account("get_balance", {
                "account_id": req["account_id"], "account_type": req["account_type"]})
            if res.get("status") != "ok":
                return f"Sorry, I couldn't get that balance: {_explain(res.get('reason'))}."
            return f"The balance of {res['type']} account {res['account_id']} is {_money(res['balance'])}."

        if intent == "view_transactions":
            res = self._ask_account("get_transactions", {
                "account_id": req["account_id"], "account_type": req["account_type"]})
            if res.get("status") != "ok":
                return f"Sorry, I couldn't get the transactions: {_explain(res.get('reason'))}."
            rows = "; ".join(f"{t['date']} {t['desc']} {_money(t['amount'])}" for t in res["transactions"])
            return f"Recent transactions on {res['account_id']}: {rows or 'none'}."

        if intent == "transfer":
            return self._transfer(req)

        if intent == "help":
            return ("I can show balances and recent transactions, and make transfers from your "
                    "accounts. Try: 'What's my checking balance?' or 'Send $50 to ACC-2001'.")
        return "Sorry, I didn't understand. You can ask for a balance, recent transactions, or a transfer."

    # ---------------------------------------------------------------- transfer
    def _transfer(self, req: dict[str, Any]) -> str:
        if not req.get("amount") or not (req.get("to_account") or req.get("to_type")):
            return "Please tell me the amount and the destination account, e.g. 'Send $50 to ACC-2001'."
        frm, to = req.get("from_account"), req.get("to_account")
        if not frm or not to:
            accts = self._ask_account("list_my_accounts", {})
            if accts.get("status") != "ok":
                return f"Sorry, I couldn't look up your accounts: {_explain(accts.get('reason'))}."
            mine = {a["type"]: a["account_id"] for a in accts.get("accounts", [])}
            if not frm:
                wanted = req.get("from_type") or ("savings" if req.get("to_type") == "checking" else "checking")
                if wanted not in mine:
                    return f"I couldn't find a {wanted} account on your profile."
                frm = mine[wanted]
            if not to:
                if req["to_type"] not in mine:
                    return f"I couldn't find a {req['to_type']} account on your profile."
                to = mine[req["to_type"]]
        if frm == to:
            return "The source and destination accounts are the same, so there is nothing to transfer."
        details = {"from_account": frm, "to_account": to, "amount": req["amount"]}

        if req.get("skip_review"):
            # PHASE-1 GAP (breaks P8, P9): an "express" shortcut left over from early
            # development.  If the customer asks to skip the review, the Concierge goes
            # straight to the AccountAgent without RiskAgent approval or confirmation.
            self.think("Customer asked to skip the security review; using express path "
                       "straight to AccountAgent.")
            return self._execute(details, approval_id=None)

        self.think(f"Asking RiskAgent to review transfer of {_money(details['amount'])} "
                   f"{frm} -> {details['to_account']}.")
        risk = self.send("RiskAgent", "assess_transfer", {"customer_id": self.customer_id, **details})
        if risk["decision"] == "deny":
            return "I can't make this transfer: " + "; ".join(risk["reasons"]) + "."
        if risk["decision"] == "confirmation_required":
            self.pending_ref = risk["ref"]
            return (f"Please confirm: send {_money(details['amount'])} from {frm} to {details['to_account']}? "
                    f"(Review required because: {'; '.join(risk['reasons'])}.) Reply YES to confirm or NO to cancel.")
        return self._execute(details, approval_id=risk["approval_id"])

    def _finish_pending(self, confirmed: bool) -> str:
        if not self.pending_ref:
            return "There is nothing waiting for confirmation."
        ref, self.pending_ref = self.pending_ref, None
        risk = self.send("RiskAgent", "confirm_transfer",
                         {"ref": ref, "customer_id": self.customer_id, "customer_confirmed": confirmed})
        if risk["decision"] == "cancelled":
            return "OK, the transfer was cancelled. No money was moved."
        if risk["decision"] != "approve":
            return "The transfer could not be approved: " + "; ".join(risk.get("reasons", [])) + "."
        details = {k: risk[k] for k in ("from_account", "to_account", "amount")}
        return self._execute(details, approval_id=risk["approval_id"])

    def _execute(self, details: dict[str, Any], approval_id: str | None) -> str:
        res = self._ask_account("execute_transfer", {**details, "approval_id": approval_id})
        if res.get("status") != "completed":
            return f"The transfer failed: {_explain(res.get('reason'))}. No money was moved."
        return (f"Done. Sent {_money(details['amount'])} from {details['from_account']} to "
                f"{details['to_account']} (transfer {res['transfer_id']}). "
                f"New balance: {_money(res['new_balance'])}.")
