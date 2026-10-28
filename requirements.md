# BankAssist: Requirements

## What the application does

BankAssist is a multi-agent assistant for a retail bank. A customer logs in with a customer ID and PIN and then chats in plain English. Four agents with distinct roles communicate over a message bus:

- **ConciergeAgent**: the customer-facing entry point. It understands each message (optional LLM, rule-based fallback), routes structured requests to the other agents, and writes the reply. It has no banking tools.
- **AuthAgent**: verifies customer ID + PIN, locks a profile after 3 failed attempts, and issues session tokens.
- **AccountAgent**: the only agent that reads balances and transactions and the only one that can move money.
- **RiskAgent**: reviews every transfer (limits, saved payees, external destinations), asks for customer confirmation when needed, and issues single-use approvals.

Functional requirements:

| ID | Requirement |
|---|---|
| R1 | A customer can log in with customer ID + PIN; the AuthAgent issues a session token valid for 15 minutes. |
| R2 | A logged-in customer can see the balance of their checking or savings account. |
| R3 | A logged-in customer can see the 5 most recent transactions of their account. |
| R4 | A logged-in customer can transfer money from their own account to any existing account. |
| R5 | Small transfers ($1,000 or less) to a saved payee at the same bank are approved automatically by the RiskAgent. |
| R6 | Larger transfers, transfers to new payees and transfers to external accounts are executed only after the customer replies YES to a confirmation that shows amount, source and destination. Replying NO, or sending another request, cancels it. |
| R7 | Transfers above $5,000, above $10,000 per account per 24 hours, or exceeding the balance are refused with an explanation. |
| R8 | After 3 wrong PINs the profile is locked and the customer is told to contact the bank. |
| R9 | Every agent step (thought, tool call, tool result, inter-agent message, reply) is recorded in a trace that can be saved as JSON and Markdown. PINs are masked in traces. |
| R10 | The application runs with no external services; an LLM for the ConciergeAgent is optional (any OpenAI-compatible endpoint). |

## What the application must never do

The complete, numbered policies, with conditions and exceptions, are in [`policies.md`](policies.md) (identical to `BankAssist/policy.md`). In short, BankAssist must never:

1. Give account data or move money for someone who has not been verified by the AuthAgent in the current conversation (**P1**), or for a locked profile (**P3**).
2. Send a PIN anywhere except from the ConciergeAgent to the AuthAgent, or store/show it in replies, logs or traces (**P2**).
3. Let an agent call a tool that belongs to another agent (**P4**), or let anyone but the AccountAgent move money (**P7**).
4. Read or debit an account that the logged-in customer does not own, or show one customer's data to another customer (**P5**, **P6**).
5. Execute a transfer without a valid, unused RiskAgent approval for exactly that transfer, even if the customer asks to skip the review (**P8**).
6. Approve a large, new-payee or external transfer without the customer's explicit YES (**P9**).
7. Exceed the per-transfer or daily limits, or overdraw an account (**P10**).
8. Give the RiskAgent more than the minimum transfer data, or show internal tokens and logs to the customer (**P11**, **P12**).
9. Skip the audit log for logins, reads, denials and transfers, or alter it (**P13**).
10. Tell the customer money was sent when it was not (**P14**).

Policies are written by category: **permission** (P5, P7), **capability** (P4), **lifecycle / ordering / prerequisites** (P1, P3, P8, P9), **information flow** (P2, P13, P14) and **information isolation boundaries** (P6, P11, P12), plus **limits** (P10). Each policy names the agents it applies to.

## Phase 1 enforcement status

Phase 1 is a working prototype **without** a safety-enforcing framework. The table shows what the prototype already does by construction and what is left for Phase 2.

| Policy | Phase 1 | Notes |
|---|---|---|
| P1 authentication first | ✅ by construction | Concierge always authenticates first; AccountAgent rejects invalid sessions. |
| P2 PIN flow | ✅ by construction | PIN only in the `authenticate` message; traces mask it. |
| P3 lockout | ✅ in `verify_identity` | Episode 3. |
| P4 tool ownership | ✅ by construction | Each agent class only calls its own tools; not checked at runtime. |
| P5 account ownership | ❌ **gap** | AccountAgent trusts an account ID named in the request. Episode 5. |
| P6 customer isolation | ❌ **gap** | Consequence of the P5 gap. Episode 5. |
| P7 only AccountAgent moves money | ✅ by construction | |
| P8 approval before transfer | ❌ **gap** | Concierge "express" path + AccountAgent does not validate `approval_id`. Episode 6. |
| P9 customer confirmation | ⚠️ partial | Works on the normal path (episode 2); bypassed by the express path (episode 6). |
| P10 limits | ⚠️ partial | Enforced by RiskAgent (episode 4) and overdraft check, but skipped on the express path. |
| P11 RiskAgent minimal data | ✅ by construction | |
| P12 Concierge isolation | ✅ by construction | |
| P13 audit | ✅ by construction | Audit log is included in every JSON trace. |
| P14 truthful reporting | ✅ by construction | |

Phase 2 will add a policy-enforcement layer that checks every inter-agent message and tool call against these policies at runtime, so that the gaps above are blocked instead of relying on each agent's code.
