"""Run every scripted scenario and write traces + episode files.

    python3 -m bankassist.run_scenarios            # from the src/ directory

Writes (paths relative to the repository root):
    traces/phase1/<scenario>.json    full machine-readable trace
    traces/phase1/<scenario>.md      the same trace as a Markdown table
    traces/README.md                 overview of every scenario and policy
    traces/viewer.html               swim-lane viewer of all traces (open in a browser)
    BankAssist/episodes/exampleN.md  episode write-ups (submission format)
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .app import BankAssistApp
from .bank import Bank
from .policy_audit import ALL_POLICIES, audit, summary
from .scenarios import SCENARIOS
from .trace import Tracer
from .viewer import build_viewer

REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIO_DATE = "2026-10-28"  # fixed "today" so the traces are identical on every run


def run_scenario(sc: dict) -> tuple[Tracer, list[dict]]:
    tracer = Tracer(sc["id"], sc["title"], sc["description"])
    app = BankAssistApp(tracer=tracer, bank=Bank(today=SCENARIO_DATE))
    transcript = []
    for conv in sc["conversations"]:
        app.new_conversation()
        for text in conv["turns"]:
            reply = app.chat(conv["customer_id"], conv["pin"], text)
            transcript.append({"customer_id": conv["customer_id"], "user": text, "assistant": reply})
    tracer.meta["policies"] = ", ".join(sc["policies"])
    tracer.meta["expected"] = sc["expected"]
    tracer.meta["phase1_result"] = sc["phase1_result"]
    tracer.meta["audit_log"] = app.bank.audit_log
    findings = audit(tracer.to_dict())
    tracer.meta["policy_audit"] = [asdict(f) for f in findings]
    found = sorted({f.policy for f in findings}, key=lambda p: int(p[1:]))
    if found != sorted(sc["violated"], key=lambda p: int(p[1:])):
        raise SystemExit(f"{sc['id']}: auditor found {found}, scenario declares {sc['violated']}")
    return tracer, transcript


def _findings_md(tracer: Tracer) -> list[str]:
    found = tracer.meta.get("policy_audit", [])
    if not found:
        return ["The offline auditor (`python3 -m bankassist.policy_audit`) checked this trace against "
                "P1–P16 and found **no violations**."]
    lines = ["The offline auditor (`python3 -m bankassist.policy_audit`) reports:", "",
             "| Policy | Step | Agent | What happened |", "|---|---|---|---|"]
    lines += [f"| **{f['policy']}** | {f['step']} | {f['agent']} | {f['detail']} |" for f in found]
    return lines


# ------------------------------------------------------------------ episodes
def _step_line(e: dict) -> str:
    a, k = e["agent"], e["kind"]
    if k == "user_input":
        return f"**User → {e['to']}**: \"{e['content']}\""
    if k == "thought":
        return f"**{a}** (thought): {e['content']}"
    if k == "action":
        return f"**{a}** calls `{e['tool']}` with `{json.dumps(e['args'])}`"
    if k == "observation":
        return f"**{a}** observes `{e['tool']}` → `{json.dumps(e['result'])}`"
    if k == "message":
        return f"**{a} → {e['to']}** `{e['performative']}`: `{json.dumps(e['payload'])}`"
    if k == "response":
        return f"**{a} → User**: \"{e['content']}\""
    return json.dumps(e)


def episode_markdown(n: int, sc: dict, tracer: Tracer) -> str:
    lines = [f"# Example {n}: {sc['title']}", "",
             "_Real episode: produced by running the Phase 1 prototype "
             f"(`python3 -m bankassist.run_scenarios`). Full trace: `traces/phase1/{sc['id']}.json`._", "",
             "## Initial Inputs", "", sc["description"], ""]
    for i, conv in enumerate(sc["conversations"], 1):
        lines.append(f"- Conversation {i}: login as customer `{conv['customer_id']}` with PIN `****` "
                     f"({'correct' if _pin_ok(conv) else 'wrong'} PIN). Received by **ConciergeAgent**.")
        for t in conv["turns"]:
            lines.append(f"  - Customer message: \"{t}\"")
    lines += ["", "## Trajectory", "",
              "_Step numbers match the full JSON trace; `record_audit` calls are left out here for "
              "readability._", ""]
    for e in tracer.events:
        if e["kind"] == "action" and e["tool"] == "record_audit":
            continue  # audit writes are kept in the JSON trace, omitted here for readability
        if e["kind"] == "observation" and e["tool"] == "record_audit":
            continue
        lines.append(f"{e['step']}. {_step_line(e)}")
    lines += ["", "## Policy Connection", "",
              ", ".join(sc["policies"]) + " (see `policy.md`).", ""]
    lines += [f"- {a}" for a in sc["analysis"]]
    lines += ["",
              "## Expected Outcome", "", sc["expected"], "",
              "## Actual Phase 1 Outcome", "", sc["phase1_result"], "",
              "## Offline Policy Audit", ""]
    lines += _findings_md(tracer)
    lines.append("")
    return "\n".join(lines)


def _pin_ok(conv: dict) -> bool:
    from .bank import SEED_DATA
    return SEED_DATA["customers"][conv["customer_id"]]["pin"] == conv["pin"]


# ---------------------------------------------------------------- README
def traces_readme(results: list[tuple[dict, Tracer, list[dict]]]) -> str:
    lines = [
        "# Traces",
        "",
        "Every trace in `phase1/` was produced by running the Phase 1 prototype:",
        "",
        "```bash",
        "cd src && python3 -m bankassist.run_scenarios",
        "```",
        "",
        "Each scenario has two files: `<scenario>.json` (complete machine-readable trace) and "
        "`<scenario>.md` (the same trace as a table). A trace records every:",
        "",
        "- **user_input**: what the customer typed, and which agent received it",
        "- **thought**: an agent's reasoning or decision",
        "- **action**: a tool call, with its arguments",
        "- **observation**: what the tool returned",
        "- **message**: an inter-agent message (request or reply) on the message bus",
        "- **response**: the final text shown to the customer",
        "",
        "For a visual walk-through, download and open [`viewer.html`](viewer.html) in a browser: it shows "
        "every trace as a swim-lane timeline (one column per agent) that can be stepped through event by event.",
        "",
        "All committed traces use the rule-based Concierge (`concierge_mode: rules`) so that they are "
        "reproducible byte for byte; set `BANKASSIST_LLM_BASE_URL` / `BANKASSIST_LLM_MODEL` to record "
        "the same scenarios with an LLM (see `src/README.md`). The `thought` events of the rule-based "
        "agents are decision logs written by the code path that was actually taken.",
        "",
        "PINs are masked as `****` in every trace (policy P2). The JSON `meta.audit_log` holds the "
        "bank's audit log at the end of the run (policy P13).",
        "",
        "Phase 1 is the prototype **without** a safety-enforcing framework. Scenarios 1–4 show "
        "correct behaviour; scenarios 5–7 show policy violations that the Phase 1 prototype "
        "does not prevent. These will be blocked in Phase 2.",
        "",
        "**Which policy was triggered** is not only described by hand: every trace was also checked "
        "by an offline auditor (`src/bankassist/policy_audit.py`), which reads the finished JSON and "
        "reports each violated policy with the exact step and agent. It only reads traces and blocks "
        "nothing, so Phase 1 still has no enforcement. Re-check any trace with:",
        "",
        "```bash",
        "cd src && python3 -m bankassist.policy_audit ../traces/phase1/*.json",
        "```",
        "",
        "## Summary",
        "",
        "| # | Scenario | Policies involved | Auditor: violated at step | Phase 1 result |",
        "|---|---|---|---|---|",
    ]
    for i, (sc, tr, _) in enumerate(results, 1):
        status = "❌ violation" if sc["violation"] else "✅ compliant"
        found = tr.meta.get("policy_audit", [])
        where = ", ".join(f"**{f['policy']}** @ {f['step']}" for f in found) or "none"
        lines.append(f"| {i} | [{sc['title']}](phase1/{sc['id']}.md) | {', '.join(sc['policies'])} | "
                     f"{where} | {status} |")
    lines += ["", "### Policy × scenario (offline audit)", "",
              "✅ = checked, not violated · ❌ = violated · – = not observable in a trace (P17: data sent to "
              "an external LLM). A ✅ covers what a trace shows; approval age (P8), the confirmation window "
              "and same-customer binding (P9), overdrafts (P10), audit-entry contents (P13) and the "
              "\"no money was moved\" wording (P14) are checked by unit tests instead.", "",
              "| Policy | " + " | ".join(str(i) for i in range(1, len(results) + 1)) + " |",
              "|---|" + "---|" * len(results)]
    sums = [summary(f["policy"] for f in tr.meta.get("policy_audit", [])) for _, tr, _ in results]
    for p in ALL_POLICIES:
        marks = {"ok": "✅", "violated": "❌", "not observable": "–"}
        lines.append(f"| {p} | " + " | ".join(marks[sm[p]] for sm in sums) + " |")
    lines.append("")
    for i, (sc, tr, transcript) in enumerate(results, 1):
        lines += [f"## {i}. {sc['title']}", "",
                  f"Files: [`phase1/{sc['id']}.json`](phase1/{sc['id']}.json), "
                  f"[`phase1/{sc['id']}.md`](phase1/{sc['id']}.md) · {len(tr.events)} trace events", "",
                  f"**Scenario.** {sc['description']}", "",
                  "**Conversation.**", ""]
        for t in transcript:
            lines.append(f"> **{t['customer_id']}:** {t['user']}  ")
            lines.append(f"> **BankAssist:** {t['assistant']}")
            lines.append(">")
        if lines[-1] == ">":
            lines.pop()
        lines += ["", f"**Policies involved.** {', '.join(sc['policies'])}", ""]
        lines += [f"- {a}" for a in sc["analysis"]]
        lines += ["",
                  f"**Expected (per policy.md).** {sc['expected']}", "",
                  f"**Phase 1 result.** {sc['phase1_result']}", "",
                  "**Offline audit.**", ""]
        lines += _findings_md(tr)
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(REPO_ROOT), help="repository root to write into")
    args = ap.parse_args(argv)
    root = Path(args.root)
    trace_dir, ep_dir = root / "traces" / "phase1", root / "BankAssist" / "episodes"
    trace_dir.mkdir(parents=True, exist_ok=True)
    ep_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for n, sc in enumerate(SCENARIOS, 1):
        tracer, transcript = run_scenario(sc)
        tracer.save_json(str(trace_dir / f"{sc['id']}.json"))
        tracer.save_markdown(str(trace_dir / f"{sc['id']}.md"))
        (ep_dir / f"example{n}.md").write_text(episode_markdown(n, sc, tracer), encoding="utf-8")
        results.append((sc, tracer, transcript))
        flag = "VIOLATION" if sc["violation"] else "ok"
        print(f"[{flag:9}] {sc['id']:32} {len(tracer.events):3} events")
        for t in transcript:
            print(f"     {t['customer_id']}: {t['user']}")
            print(f"     BankAssist: {t['assistant']}")
    (root / "traces" / "README.md").write_text(traces_readme(results), encoding="utf-8")
    (root / "traces" / "viewer.html").write_text(build_viewer([tr.to_dict() for _, tr, _ in results]),
                                                 encoding="utf-8")
    print(f"\nWrote {len(results)} traces to {trace_dir} and episodes to {ep_dir}")


if __name__ == "__main__":
    main()
