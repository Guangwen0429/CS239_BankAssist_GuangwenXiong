"""Trace recorder.

Every agent thought, tool call (action), tool result (observation) and
inter-agent message is appended to a Tracer.  A finished trace can be saved
as JSON (machine-readable) and as Markdown (human-readable).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

EVENT_KINDS = (
    "user_input",   # text typed by the human customer
    "thought",      # an agent's reasoning / decision
    "action",       # an agent calls a tool
    "observation",  # the result the tool returned
    "message",      # one agent sends a message to another agent
    "response",     # final text shown to the human customer
)


SECRET_KEYS = {"pin"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def redact(obj: Any) -> Any:
    """Return a copy of obj with secret fields (PINs) masked, so traces never store them."""
    if isinstance(obj, dict):
        return {k: ("****" if k in SECRET_KEYS else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


class Tracer:
    def __init__(self, scenario_id: str = "interactive", title: str = "", description: str = ""):
        self.scenario_id = scenario_id
        self.title = title
        self.description = description
        self.started_at = _now()
        self.events: list[dict[str, Any]] = []
        self.meta: dict[str, Any] = {}

    # ------------------------------------------------------------------ record
    def _add(self, kind: str, agent: str, **fields: Any) -> dict[str, Any]:
        assert kind in EVENT_KINDS, kind
        event = {"step": len(self.events) + 1, "time": _now(), "kind": kind, "agent": agent}
        event.update(redact(fields))
        self.events.append(event)
        return event

    def user_input(self, text: str, to: str) -> None:
        self._add("user_input", "User", to=to, content=text)

    def thought(self, agent: str, text: str) -> None:
        self._add("thought", agent, content=text)

    def action(self, agent: str, tool: str, args: dict[str, Any]) -> None:
        self._add("action", agent, tool=tool, args=args)

    def observation(self, agent: str, tool: str, result: Any) -> None:
        self._add("observation", agent, tool=tool, result=result)

    def message(self, sender: str, recipient: str, performative: str, payload: dict[str, Any]) -> None:
        self._add("message", sender, to=recipient, performative=performative, payload=payload)

    def response(self, agent: str, text: str) -> None:
        self._add("response", agent, to="User", content=text)

    # ------------------------------------------------------------------ export
    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "title": self.title,
            "description": self.description,
            "started_at": self.started_at,
            "meta": self.meta,
            "events": self.events,
        }

    def save_json(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
            f.write("\n")

    def to_markdown(self) -> str:
        lines = [f"# Trace `{self.scenario_id}`: {self.title}", ""]
        if self.description:
            lines += [self.description, ""]
        for key, value in self.meta.items():
            if key != "audit_log":
                lines.append(f"- **{key}:** {value}")
        if self.meta:
            lines.append("")
        lines += ["| # | Agent | Kind | Detail |", "|---|---|---|---|"]
        for e in self.events:
            lines.append(f"| {e['step']} | {e['agent']} | {e['kind']} | {_md_detail(e)} |")
        lines.append("")
        audit = self.meta.get("audit_log")
        if audit:
            lines += ["## Audit log at end of run", "", "| seq | agent | event | details |", "|---|---|---|---|"]
            for a in audit:
                lines.append(f"| {a['seq']} | {a['agent']} | {a['event']} | `{_short(a['details'])}` |")
            lines.append("")
        return "\n".join(lines)

    def save_markdown(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_markdown())


def _short(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(", ", ": "))


def _md_detail(e: dict[str, Any]) -> str:
    kind = e["kind"]
    if kind == "user_input":
        text = f"→ {e['to']}: \"{e['content']}\""
    elif kind in ("thought",):
        text = f"_{e['content']}_"
    elif kind == "response":
        text = f"→ User: \"{e['content']}\""
    elif kind == "action":
        text = f"`{e['tool']}({_short(e['args'])})`"
    elif kind == "observation":
        text = f"`{e['tool']}` → `{_short(e['result'])}`"
    elif kind == "message":
        text = f"→ **{e['to']}** [{e['performative']}] `{_short(e['payload'])}`"
    else:  # pragma: no cover
        text = _short(e)
    return text.replace("|", "\\|").replace("\n", " ")
