"""Interactive command-line chat with BankAssist.

    python3 -m bankassist.cli                 # from the src/ directory
    python3 -m bankassist.cli --show-trace    # also print every agent step live
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import time
from pathlib import Path

from .app import BankAssistApp
from .bank import SEED_DATA
from .trace import Tracer, _md_detail

REPO_ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Chat with the BankAssist multi-agent assistant.")
    ap.add_argument("--show-trace", action="store_true", help="print agent thoughts, tool calls and messages")
    ap.add_argument("--customer", help="customer ID (otherwise prompted)")
    ap.add_argument("--pin", help="PIN (otherwise prompted, hidden)")
    args = ap.parse_args(argv)

    tracer = Tracer("interactive", "Interactive session")
    app = BankAssistApp(tracer=tracer)
    print("BankAssist (Phase 1 prototype) · Concierge mode:", tracer.meta["concierge_mode"])
    print("Demo customers:", ", ".join(f"{cid} ({c['name']})" for cid, c in SEED_DATA["customers"].items()))
    print("Demo PINs: C001=1234, C002=5678, C003=2468.  Type 'logout' to switch user, 'quit' to exit.\n")

    try:
        customer = (args.customer or input("Customer ID: ")).strip().upper()
        pin = (args.pin or getpass.getpass("PIN: ")).strip()
        shown = 0
        while True:
            text = input(f"{customer}> ").strip()
            if not text:
                continue
            if text.lower() in ("quit", "exit"):
                break
            if text.lower() == "logout":
                app.new_conversation()
                customer = input("Customer ID: ").strip().upper()
                pin = getpass.getpass("PIN: ").strip()
                continue
            reply = app.chat(customer, pin, text)
            if args.show_trace:
                for e in tracer.events[shown:]:
                    if e["kind"] not in ("user_input", "response"):
                        print(f"   [{e['step']:>3}] {e['agent']:<14} {e['kind']:<11} {_md_detail(e)}")
            shown = len(tracer.events)
            print(f"BankAssist: {reply}\n")
            if app.concierge.session_token is None:
                # login failed: never resend the same PIN automatically (P1, P3)
                print("Not logged in. Enter the PIN again (or type 'logout' to switch customer).")
                pin = getpass.getpass("PIN: ").strip()
                if pin.lower() == "logout":
                    app.new_conversation()
                    customer = input("Customer ID: ").strip().upper()
                    pin = getpass.getpass("PIN: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()

    out_dir = REPO_ROOT / "traces" / "interactive"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"session-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}.json"
    tracer.meta["audit_log"] = app.bank.audit_log
    tracer.save_json(str(path))
    print(f"Trace saved to {path}")


if __name__ == "__main__":
    main()
