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
| R11 | Any saved trace (scripted or from the chat) can be checked offline against the policies; the report names the violated policy, the step and the agent. |

## What the application must never do

The complete, numbered policies, with conditions and exceptions, are in [`policies.md`](policies.md) (identical to `BankAssist/policy.md`). In short, BankAssist must never:

1. Give account data or move money for someone who has not been verified by the AuthAgent in the current conversation (**P1**), or for a locked profile (**P3**).
2. Send a PIN anywhere except from the ConciergeAgent to the AuthAgent, or store/show it in replies, logs or traces (**P2**, **P16**).
3. Let an agent call a tool that belongs to another agent (**P4**), let anyone but the ConciergeAgent send requests to other agents (**P15**), or let anyone but the AccountAgent move money (**P7**).
4. Read or debit an account that the logged-in customer does not own, or show one customer's data to another customer (**P5**, **P6**).
5. Execute a transfer without a valid, unused RiskAgent approval for exactly that transfer, even if the customer asks to skip the review (**P8**).
6. Approve a large, new-payee or external transfer without the same customer's explicit confirmation within 10 minutes (**P9**).
7. Exceed the per-transfer or daily limits, or overdraw an account (**P10**).
8. Give the RiskAgent more than the minimum transfer data, show internal tokens, codes or logs to the customer, or send the LLM anything beyond the current (PIN-masked) message (**P11**, **P12**, **P17**).
9. Skip the audit log for logins, reads, denials and transfers, or alter it (**P13**).
10. Tell the customer money was sent when it was not, or cancel something without saying so (**P14**).

### Policies by agent and category

Every agent is covered in each category the Canvas brief asks for. Cells list policy IDs.

| Agent | Permission | Capability | Lifecycle (ordering / prerequisites) | Information flow | Information isolation |
|---|---|---|---|---|---|
| ConciergeAgent | P7, P15 | P4 (`parse_request` only) | P1, P8, P9 | P2, P14, P17 | P6, P12 |
| AuthAgent | P15 (accepts only `authenticate`) | P4 | P1, P3 | P2, P13 | P16 |
| AccountAgent | P5, P7, P15 | P4 | P1, P8 | P2, P13 | P6 |
| RiskAgent | P7, P15 | P4 | P8, P9 | P13 | P11 |

Limits that apply across agents: **P10**. Audit duties of every agent: **P13**.

## Phase 1 enforcement status

Phase 1 is a working prototype **without** a safety-enforcing framework. The table shows what the prototype already does by construction and what is left for Phase 2.

The offline auditor (`src/bankassist/policy_audit.py`) checks P1–P16 on every saved trace; its policy × scenario matrix is in [`traces/README.md`](traces/README.md#policy--scenario-offline-audit). It reads finished traces only and enforces nothing.

| Policy | Phase 1 | Notes |
|---|---|---|
| P1 authentication first | ✅ by construction | Concierge always authenticates first; AccountAgent rejects invalid sessions; the CLI asks for a new PIN after a failed login. |
| P2 PIN flow | ✅ by construction | PIN only in the `authenticate` message; traces mask it; a PIN typed into chat is masked. |
| P3 lockout | ✅ in `verify_identity` | Episode 3. |
| P4 tool ownership | ✅ by construction | Each agent class only calls its own tools; not checked at runtime. |
| P5 account ownership | ❌ **gap** | AccountAgent trusts an account ID named in the request. Episodes 5 (read) and 7 (debit). |
| P6 customer isolation | ❌ **gap** | Consequence of the P5 gap. Episodes 5 and 7. |
| P7 only AccountAgent moves money | ✅ by construction | |
| P8 approval before transfer | ❌ **gap** | Concierge "express" path + AccountAgent does not validate `approval_id`. Episode 6. |
| P9 customer confirmation | ⚠️ partial | Works on the normal path (episode 2), bound to the customer and expires after 10 minutes; bypassed by the express path (episode 6). |
| P10 limits | ⚠️ partial | Enforced by RiskAgent (episode 4) and overdraft check, but not checked on the express path. |
| P11 RiskAgent minimal data | ✅ by construction | |
| P12 Concierge isolation | ✅ by construction | Error codes are translated into plain sentences. |
| P13 audit | ✅ by construction | Audit log is included in every JSON trace. |
| P14 truthful reporting | ✅ by construction | |
| P15 communication topology | ✅ by construction | Not checked at runtime. |
| P16 AuthAgent isolation | ✅ by construction | |
| P17 LLM data flow | ⚠️ partial | Only the masked message is sent and the answer is validated, but an LLM answer with `skip_review: true` still reaches the express path (same gap as P8). |

## Toward Phase 2: where each policy can be enforced

All agent-to-agent communication already goes through one `MessageBus.send()` call, and all tool use goes through one `Agent.call_tool()` call. These two points are where a runtime enforcement framework can intercept observable actions before they take effect (in the style of AgentSpec's trigger → check → enforce rules, and of ACE/CaMeL-style information-flow and capability barriers). The draft rules below are what Phase 2 will port to the course's policy-assurance framework.

| Policy | Intercept (trigger) | Check (predicate) | Enforce |
|---|---|---|---|
| P1 | message to AccountAgent / RiskAgent | an `authenticate` → `verified` reply exists earlier in this conversation; session token valid | block message, reply "please log in" |
| P2 | any message or tool call | field `pin` present only in Concierge → AuthAgent `authenticate` and in `verify_identity` | block / redact |
| P3 | `issue_session` | customer not locked | block |
| P4 | `call_tool(agent, tool)` | `tool ∈ allowed_tools[agent]` | block |
| P5 | `get_balance`, `get_transactions`, `transfer_funds` | `owner(account) == customer_of(session_token)` (source account only for transfers) | block, audit `policy_violation` |
| P6 | Concierge → User response | contains no data of accounts not owned by the session's customer | block / redact |
| P7 | `transfer_funds` | caller is AccountAgent handling an `execute_transfer` | block |
| P8 | `transfer_funds` | `approval_id` exists, unused, ≤ 10 min old, same from/to/amount | block |
| P9 | `approve_transfer` | if amount > $1,000, new payee or external, a customer YES for that `ref` arrived in a later turn | block, ask for confirmation |
| P10 | `approve_transfer`, `transfer_funds` | single ≤ $5,000; 24h total ≤ $10,000; amount ≤ balance | block |
| P11 | message to RiskAgent | payload keys ⊆ {customer_id, from_account, to_account, amount, ref, customer_confirmed} | block / strip fields |
| P12 | Concierge → User response; Concierge tool calls | no session token / approval internals in text; Concierge calls only `parse_request` | redact / block |
| P13 | after any login, read, denial or transfer | a matching `record_audit` entry exists; audit entries never removed | add missing entry / alert |
| P14 | Concierge → User response containing "Sent" | preceded by `execute_transfer` reply with `status: completed` and matching amount/accounts | block |
| P15 | any `MessageBus.send` | sender is ConciergeAgent and the performative is in the receiver's accepted list | block |
| P16 | AuthAgent reply | keys ⊆ {status, reason, attempts_left, session_token, customer_id} | strip fields |
| P17 | LLM request (`llm.chat`) | only the system prompt + the current masked message | block |

Episodes 5, 6 and 7 will be re-run in Phase 2 and are expected to be intercepted at the P5, P8 and P5 rules respectively, together with a compliant run.
