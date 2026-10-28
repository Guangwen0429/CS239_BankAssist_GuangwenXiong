"""One-command class demo.

    python3 scripts/demo.py            # audit summary of the committed traces + open the viewer
    python3 scripts/demo.py --chat     # ... then start a live chat as Alice with the trace shown

(On Windows use `py` instead of `python3`.)  Nothing in the repository is modified.
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bankassist import cli  # noqa: E402
from bankassist.policy_audit import audit  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chat", action="store_true", help="start a live chat as C001 after the summary")
    ap.add_argument("--no-browser", action="store_true", help="do not open the trace viewer")
    args = ap.parse_args()

    print("BankAssist: Phase 1 traces and what the offline policy auditor finds\n")
    for path in sorted((ROOT / "traces" / "phase1").glob("*.json")):
        trace = json.loads(path.read_text(encoding="utf-8"))
        found = audit(trace)
        label = "no violations" if not found else ", ".join(f"{f.policy} at step {f.step}" for f in found)
        print(f"  {trace['scenario_id']:32} {len(trace['events']):3} events   {label}")

    viewer = ROOT / "traces" / "viewer.html"
    if not args.no_browser:
        print(f"\nOpening {viewer} ...")
        webbrowser.open(viewer.as_uri())

    if args.chat:
        print("\nLive chat as Alice (C001). Try: What's my checking balance? / "
              "Transfer $1,500 from savings to ACC-2001 / YES / quit\n")
        cli.main(["--customer", "C001", "--pin", "1234", "--show-trace"])


if __name__ == "__main__":
    main()
