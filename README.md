# CS239 · BankAssist · Guangwen Xiong

**BankAssist** is a multi-agent retail-banking assistant built for CS239 (Agentic Software Engineering). A customer chats in plain English to check balances, view transactions and send money. Four agents with distinct roles cooperate by exchanging messages:

```text
                 ┌──────────────┐  authenticate            ┌─────────────┐
   Customer ───► │ Concierge    │ ───────────────────────► │ AuthAgent   │  verify_identity, issue_session
   (chat)   ◄─── │ Agent        │ ◄─────────────────────── │             │  resolve_session
                 │              │                          └─────────────┘
                 │ parse_request│  assess / confirm        ┌─────────────┐
                 │ (LLM or      │ ───────────────────────► │ RiskAgent   │  check_payee, daily_transfer_total
                 │  rules)      │ ◄─────────────────────── │             │  approve_transfer
                 │              │                          └─────────────┘
                 │              │  balance / history /     ┌─────────────┐
                 │              │  execute_transfer        │ AccountAgent│  list_accounts, get_balance,
                 │              │ ───────────────────────► │             │  get_transactions, transfer_funds
                 └──────────────┘ ◄─────────────────────── └─────────────┘
```

- **Domain:** banking · **Agents:** 4 (1 optionally LLM-based, 3 rule-based) · **Tools:** 12 · **Policies:** 17
- **Runs anywhere:** Python 3.10+, standard library only, no API key needed. An LLM is optional (bring your own token/compute through any OpenAI-compatible endpoint, local or hosted).

## Quick start

```bash
git clone https://github.com/Guangwen0429/CS239_BankAssist_GuangwenXiong.git
cd CS239_BankAssist_GuangwenXiong/src
python3 -m bankassist.run_scenarios              # re-generate all traces and episodes
python3 -m bankassist.cli --show-trace           # chat (demo login: C001 / 1234)
cd .. && python3 -m unittest discover -s tests   # run the tests
```

Full setup, demo accounts and LLM configuration: [`src/README.md`](src/README.md).

## Phase 1: Prototype

| Deliverable | Where |
|---|---|
| What the app does / must never do | [`requirements.md`](requirements.md) |
| Policies (P1–P17: permission, capability, lifecycle, information flow, isolation, for each agent) | [`policies.md`](policies.md) |
| Phase 1 source code | [`src/`](src/) |
| Agent traces (7 scenarios, JSON + Markdown) | [`traces/phase1/`](traces/phase1/) |
| Scenario guide: what each trace shows and which policy is involved | [`traces/README.md`](traces/README.md) |
| Visual trace viewer (open locally in a browser) | [`traces/viewer.html`](traces/viewer.html) |
| Tests | [`tests/`](tests/) |

The seven traces:

| # | Scenario | Result |
|---|---|---|
| 1 | Balance, small transfer to a saved payee, history | ✅ compliant |
| 2 | $1,500 transfer: RiskAgent review → customer YES → approval → transfer | ✅ compliant |
| 3 | Three wrong PINs lock the profile; correct PIN then refused | ✅ compliant |
| 4 | $6,000 transfer denied by the single-transfer limit | ✅ compliant |
| 5 | Bob reads Alice's transactions by naming her account ID | ❌ violates P5, P6 |
| 6 | "Urgent, skip the security check" → transfer executed with no risk review | ❌ violates P8, P9 |
| 7 | Alice moves $500 out of Bob's account into her own | ❌ violates P5, P6 |

Phase 1 is intentionally built **without** a safety-enforcing framework, so scenarios 5–7 show real policy violations. Phase 2 will enforce the policies at runtime and the same scenarios will be blocked.

## Course submission format

This repository also follows the CS239 *Multi-Agent Application Submission Guidelines*:

```text
BankAssist/                 # Archive 1 contents: application description
├── app.md                  # purpose and supported tasks
├── policy.md               # P1–P17
├── tools.md                # every tool, its inputs and outputs
├── agents/                 # concierge.md, auth.md, account.md, risk.md
└── episodes/               # example1.md … example7.md (generated from real runs)
src/                        # source code + README.md (setup, run, examples)
tests/                      # test cases + README.md
```

The two archives are in [`submission/`](submission/) and can be rebuilt with `python3 scripts/package_submission.py`:

- `GuangwenXiong-BankAssist-406999164-requirements.tar.gz`
- `GuangwenXiong-BankAssist-406999164-whole.tar.gz`

## Phase 2: Hardening

_To be added._

## License

[MIT](LICENSE)
