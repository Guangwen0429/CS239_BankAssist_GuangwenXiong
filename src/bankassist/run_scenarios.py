"""Run every scripted scenario and write traces + episode files.

    python -m bankassist.run_scenarios            # from the src/ directory

Writes (paths relative to the repository root):
    traces/phase1/<scenario>.json    full machine-readable trace
    traces/phase1/<scenario>.md      the same trace as a Markdown table
    traces/README.md                 overview of every scenario and policy
    BankAssist/episodes/exampleN.md  episode write-ups (submission format)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .app import BankAssistApp
from .scenarios import SCENARIOS
from .trace import Tracer

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_scenario(sc: dict) -> tuple[Tracer, list[dict]]:
    tracer = Tracer(sc["id"], sc["title"], sc["description"])
    app = BankAssistApp(tracer=tracer)
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
    return tracer, transcript


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
             f"(`python -m bankassist.run_scenarios`). Full trace: `traces/phase1/{sc['id']}.json`._", "",
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
              "## Actual Phase 1 Outcome", "", sc["phase1_result"], ""]
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
        "cd src && python -m bankassist.run_scenarios",
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
        "PINs are masked as `****` in every trace (policy P2). The JSON `meta.audit_log` holds the "
        "bank's audit log at the end of the run (policy P13).",
        "",
        "Phase 1 is the prototype **without** a safety-enforcing framework. Scenarios 1–4 show "
        "correct behaviour; scenarios 5 and 6 show policy violations that the Phase 1 prototype "
        "does not prevent. These will be blocked in Phase 2.",
        "",
        "## Summary",
        "",
        "| # | Scenario | Policies involved | Phase 1 result |",
        "|---|---|---|---|",
    ]
    for i, (sc, tr, _) in enumerate(results, 1):
        status = "❌ violation" if sc["violation"] else "✅ compliant"
        lines.append(f"| {i} | [{sc['title']}](phase1/{sc['id']}.md) | {', '.join(sc['policies'])} | {status} |")
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
                  f"**Phase 1 result.** {sc['phase1_result']}", ""]
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
    print(f"\nWrote {len(results)} traces to {trace_dir} and episodes to {ep_dir}")


if __name__ == "__main__":
    main()
