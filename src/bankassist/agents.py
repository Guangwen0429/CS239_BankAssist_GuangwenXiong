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
import re
from typing import Any

from .bank import DAILY_TRANSFER_LIMIT, SINGLE_TRANSFER_LIMIT, STEP_UP_THRESHOLD, Bank
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
            cid = payload.get("customer_id", "")
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

        if performative == "validate_session":
            return self.call_tool("resolve_session", session_token=payload.get("session_token", ""))

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
        return accts[0]["account_id"] if accts else None

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
                self.think(f"No account named; using customer {cid}'s "
                           f"{payload.get('account_type') or 'checking'} account {account_id}.")
            if performative == "get_balance":
                res = self.call_tool("get_balance", account_id=account_id)
            else:
                res = self.call_tool("get_transactions", account_id=account_id, limit=5)
            self.call_tool("record_audit", agent=self.name, event=performative,
                           details={"customer_id": cid, "account_id": account_id})
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
                               details={"from": frm, "to": to, "amount": amt, "reasons": reasons_deny})
                return {"decision": "deny", "reasons": reasons_deny}
            if reasons_step:
                ref = f"RISK-{len(self.pending) + 1:03d}"
                self.pending[ref] = {"customer_id": cid, "from_account": frm, "to_account": to, "amount": amt}
                self.think("Needs customer confirmation: " + "; ".join(reasons_step) + ".")
                return {"decision": "confirmation_required", "ref": ref, "reasons": reasons_step}
            self.think("Low risk: known payee, small amount, within limits. Approving.")
            appr = self.call_tool("approve_transfer", from_account=frm, to_account=to, amount=amt)
            return {"decision": "approve", "approval_id": appr["approval_id"]}

        if performative == "confirm_transfer":
            ref = payload.get("ref")
            pend = self.pending.pop(ref, None)
            if pend is None:
                return {"decision": "deny", "reasons": ["unknown or expired reference"]}
            if not payload.get("customer_confirmed"):
                self.think(f"Customer did not confirm {ref}; cancelling.")
                return {"decision": "cancelled"}
            self.think(f"Customer confirmed {ref}; issuing approval.")
            appr = self.call_tool("approve_transfer", from_account=pend["from_account"],
                                  to_account=pend["to_account"], amount=pend["amount"])
            return {"decision": "approve", "approval_id": appr["approval_id"], **pend}

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
  "amount":        number in US dollars, no currency symbol
  "skip_review":   true only if the customer explicitly asks to skip / bypass the security or risk review

Rules:
- "yes", "confirm", "go ahead" -> intent "confirm".  "no", "cancel" -> intent "decline".
- Copy account IDs exactly as written by the customer (upper-case).
- Do not invent values the customer did not state.
- Output JSON only, no explanation."""

_ACCOUNT_RE = re.compile(r"\b(?:ACC|EXT)-\d{4}\b", re.IGNORECASE)
_AMOUNT_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{1,2})?)|([\d,]+(?:\.\d{1,2})?)\s*(?:dollars|usd)\b", re.IGNORECASE)
_INTENT_FIELDS = ("intent", "account_id", "account_type", "from_account", "from_type",
                  "to_account", "amount", "skip_review")


def rule_parse(text: str) -> dict[str, Any]:
    """Deterministic keyword/regex parser used when no LLM is configured."""
    t = text.strip()
    low = t.lower()
    out: dict[str, Any] = {k: None for k in _INTENT_FIELDS}
    out["skip_review"] = False

    if re.fullmatch(r"(yes|y|confirm|confirmed|go ahead|ok|okay)[.!]?", low):
        out["intent"] = "confirm"
        return out
    if re.fullmatch(r"(no|n|cancel|stop|don't)[.!]?", low):
        out["intent"] = "decline"
        return out

    accounts = [m.upper() for m in _ACCOUNT_RE.findall(t)]
    no_ids = _ACCOUNT_RE.sub(" ", t)
    m = _AMOUNT_RE.search(no_ids)
    if m:
        out["amount"] = float((m.group(1) or m.group(2)).replace(",", ""))

    if re.search(r"\b(transfer|send|wire|pay|move)\b", low):
        out["intent"] = "transfer"
        fm = re.search(r"from\s+(?:my\s+)?((?:acc|ext)-\d{4}|checking|savings)", low)
        tm = re.search(r"\bto\s+(?:my\s+|account\s+)?((?:acc|ext)-\d{4}|checking|savings)", low)
        if fm:
            v = fm.group(1)
            out["from_account" if "-" in v else "from_type"] = v.upper() if "-" in v else v
        if tm and "-" in tm.group(1):
            out["to_account"] = tm.group(1).upper()
        elif accounts:
            rest = [a for a in accounts if a != out["from_account"]]
            out["to_account"] = rest[-1] if rest else None
        out["skip_review"] = bool(re.search(
            r"\b(skip|bypass|without (the )?(security|risk|review|check|verification)|no (need for|review|check))",
            low))
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

    # ------------------------------------------------------------ understanding
    def parse_request(self, text: str) -> dict[str, Any]:
        mode = "llm" if llm_config() else "rules"
        self.tracer.action(self.name, "parse_request", {"text": text, "mode": mode})
        parsed = None
        if mode == "llm":
            try:
                raw = chat(CONCIERGE_SYSTEM_PROMPT, text)
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                cand = json.loads(m.group(0)) if m else None
                if isinstance(cand, dict) and cand.get("intent"):
                    parsed = {k: cand.get(k) for k in _INTENT_FIELDS}
                    parsed["skip_review"] = bool(parsed.get("skip_review"))
            except (LLMUnavailable, ValueError) as exc:
                self.think(f"LLM unavailable ({exc}); falling back to rule parser.")
        if parsed is None:
            parsed = rule_parse(text)
        self.tracer.observation(self.name, "parse_request", parsed)
        return parsed

    # --------------------------------------------------------------- one turn
    def handle_user(self, customer_id: str, pin: str, text: str) -> str:
        self.tracer.user_input(text, to=self.name)
        reply = self._turn(customer_id, pin, text)
        self.tracer.response(self.name, reply)
        return reply

    def _turn(self, customer_id: str, pin: str, text: str) -> str:
        if self.session_token is None:
            self.think("No active session; asking AuthAgent to verify the customer first.")
            auth = self.send("AuthAgent", "authenticate", {"customer_id": customer_id, "pin": pin})
            if auth["status"] != "verified":
                if auth.get("reason") == "locked":
                    return ("For your security this profile is locked after too many failed PIN "
                            "attempts. Please call 1-800-555-0100 to unlock it.")
                left = auth.get("attempts_left")
                return ("Sorry, I couldn't verify your identity, so I can't help with account requests."
                        + (f" {left} attempt(s) left before the profile is locked." if left else ""))
            self.session_token, self.customer_id = auth["session_token"], auth["customer_id"]

        req = self.parse_request(text)
        intent = req["intent"]

        if intent in ("confirm", "decline"):
            return self._finish_pending(confirmed=(intent == "confirm"))
        if self.pending_ref:
            self.think(f"New request while {self.pending_ref} is waiting; dropping the pending transfer.")
            self.pending_ref = None

        if intent == "check_balance":
            res = self.send("AccountAgent", "get_balance", {
                "session_token": self.session_token,
                "account_id": req["account_id"], "account_type": req["account_type"]})
            if res.get("status") != "ok":
                return f"Sorry, I couldn't get that balance ({res.get('reason')})."
            return f"The balance of {res['type']} account {res['account_id']} is {_money(res['balance'])}."

        if intent == "view_transactions":
            res = self.send("AccountAgent", "get_transactions", {
                "session_token": self.session_token,
                "account_id": req["account_id"], "account_type": req["account_type"]})
            if res.get("status") != "ok":
                return f"Sorry, I couldn't get the transactions ({res.get('reason')})."
            rows = "; ".join(f"{t['date']} {t['desc']} {_money(t['amount'])}" for t in res["transactions"])
            return f"Recent transactions on {res['account_id']}: {rows or 'none'}."

        if intent == "transfer":
            return self._transfer(req)

        if intent == "help":
            return ("I can show balances and recent transactions, and send transfers between "
                    "accounts. Try: 'What's my checking balance?' or 'Send $50 to ACC-2001'.")
        return "Sorry, I didn't understand. You can ask for a balance, recent transactions, or a transfer."

    # ---------------------------------------------------------------- transfer
    def _transfer(self, req: dict[str, Any]) -> str:
        if not req.get("amount") or not req.get("to_account"):
            return "Please tell me the amount and the destination account, e.g. 'Send $50 to ACC-2001'."
        frm = req.get("from_account")
        if not frm:
            accts = self.send("AccountAgent", "list_my_accounts", {"session_token": self.session_token})
            wanted = req.get("from_type") or "checking"
            match = [a["account_id"] for a in accts.get("accounts", []) if a["type"] == wanted]
            if not match:
                return f"I couldn't find a {wanted} account on your profile."
            frm = match[0]
        details = {"from_account": frm, "to_account": req["to_account"], "amount": req["amount"]}

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
        risk = self.send("RiskAgent", "confirm_transfer", {"ref": ref, "customer_confirmed": confirmed})
        if risk["decision"] == "cancelled":
            return "OK, the transfer was cancelled. No money was moved."
        if risk["decision"] != "approve":
            return "The transfer could not be approved: " + "; ".join(risk.get("reasons", [])) + "."
        details = {k: risk[k] for k in ("from_account", "to_account", "amount")}
        return self._execute(details, approval_id=risk["approval_id"])

    def _execute(self, details: dict[str, Any], approval_id: str | None) -> str:
        res = self.send("AccountAgent", "execute_transfer",
                        {"session_token": self.session_token, **details, "approval_id": approval_id})
        if res.get("status") != "completed":
            return f"The transfer failed ({res.get('reason')}). No money was moved."
        return (f"Done. Sent {_money(details['amount'])} from {details['from_account']} to "
                f"{details['to_account']} (transfer {res['transfer_id']}). "
                f"New balance: {_money(res['new_balance'])}.")
