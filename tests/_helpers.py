"""Small helpers for inspecting BankAssist traces in tests."""

from __future__ import annotations

import re
from typing import Any, Iterable

try:
    from . import _path  # noqa: F401
except ImportError:
    import _path  # noqa: F401

from bankassist.app import BankAssistApp
from bankassist.bank import SEED_DATA, Bank
from bankassist.trace import Tracer

# Tool capability table from policy P4.  record_audit is allowed for everyone.
ALLOWED_TOOLS: dict[str, set[str]] = {
    "AuthAgent": {"verify_identity", "issue_session", "resolve_session", "record_audit"},
    "AccountAgent": {"resolve_session", "list_accounts", "get_balance", "get_transactions",
                     "transfer_funds", "record_audit"},
    "RiskAgent": {"check_payee", "daily_transfer_total", "approve_transfer", "record_audit"},
    "ConciergeAgent": {"parse_request", "record_audit"},
}
BANKING_TOOLS = (ALLOWED_TOOLS["AuthAgent"] | ALLOWED_TOOLS["AccountAgent"]
                 | ALLOWED_TOOLS["RiskAgent"]) - {"record_audit"}

# Policy P11: the only fields RiskAgent may receive for a transfer review.
RISK_ASSESS_FIELDS = {"customer_id", "from_account", "to_account", "amount"}
# The confirmation follow-up carries only the RiskAgent's own reference and the YES/NO.
RISK_CONFIRM_FIELDS = {"ref", "customer_confirmed"}

SEED_PINS = {c["pin"] for c in SEED_DATA["customers"].values()}
_TOKEN_RE = re.compile(r"sess_[0-9a-f]{12}")


def new_app() -> BankAssistApp:
    return BankAssistApp(tracer=Tracer("test", "test"), bank=Bank())


def events(tracer: Tracer, kind: str | None = None, agent: str | None = None) -> list[dict]:
    return [e for e in tracer.events
            if (kind is None or e["kind"] == kind) and (agent is None or e["agent"] == agent)]


def messages(tracer: Tracer, to: str | None = None, performative: str | None = None,
             sender: str | None = None) -> list[dict]:
    return [e for e in events(tracer, "message", sender)
            if (to is None or e["to"] == to)
            and (performative is None or e["performative"] == performative)]


def actions(tracer: Tracer, tool: str | None = None, agent: str | None = None) -> list[dict]:
    return [e for e in events(tracer, "action", agent) if tool is None or e["tool"] == tool]


def turns(tracer: Tracer) -> list[list[dict]]:
    """Split the event list into one chunk per user turn (user_input .. response)."""
    out: list[list[dict]] = []
    for e in tracer.events:
        if e["kind"] == "user_input":
            out.append([])
        if out:
            out[-1].append(e)
    return out


def walk_strings(obj: Any, path: str = "") -> Iterable[tuple[str, str, str]]:
    """Yield (path, key, string) for every string value in a nested structure."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str):
                yield f"{path}.{k}", k, v
            else:
                yield from walk_strings(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, str):
                yield f"{path}[{i}]", "", v
            else:
                yield from walk_strings(v, f"{path}[{i}]")


def walk_pin_fields(obj: Any, path: str = "") -> Iterable[tuple[str, Any]]:
    """Yield (path, value) for every field literally named 'pin'."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "pin":
                yield f"{path}.{k}", v
            yield from walk_pin_fields(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_pin_fields(v, f"{path}[{i}]")


def find_pin_leaks(obj: Any, pins: Iterable[str]) -> list[str]:
    """Return a description of every place a PIN appears unmasked in obj."""
    leaks = []
    for p, v in walk_pin_fields(obj):
        if v != "****":
            leaks.append(f"{p} = {v!r}")
    patterns = [re.compile(rf"(?<!\d){re.escape(pin)}(?!\d)") for pin in pins]
    for p, key, s in walk_strings(obj):
        if key in ("time", "started_at"):
            continue  # ISO timestamps, not user data
        s = _TOKEN_RE.sub("sess_<token>", s)  # random hex, could contain any 4 digits
        for pat in patterns:
            if pat.search(s):
                leaks.append(f"{p} contains PIN {pat.pattern!r}: {s!r}")
    return leaks
