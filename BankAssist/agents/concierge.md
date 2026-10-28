# ConciergeAgent

**Kind:** LLM-based (optional) with a rule-based fallback. Implementation: `ConciergeAgent` in `src/bankassist/agents.py`.

**Available tools:** `parse_request`, `record_audit` (not used in Phase 1). It has no banking tools; to get anything done it sends messages to AuthAgent, AccountAgent and RiskAgent.

**Role.** The single customer-facing entry point. For every customer message it (1) makes sure the customer is logged in by asking AuthAgent, (2) turns the free text into a structured request with `parse_request`, (3) routes the request to the right agent(s), and (4) writes the reply to the customer.

## System prompt (used by `parse_request` when an LLM is configured)

This is the exact prompt in the code (`CONCIERGE_SYSTEM_PROMPT`). The customer's message is sent as the user message, and the JSON object in the answer is used as the parsed request.

```text
You are the Concierge of BankAssist, a retail-banking assistant.
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
- Output JSON only, no explanation.
```

When no LLM is configured (the default), or the LLM call fails or returns no usable JSON, `parse_request` uses the deterministic rule parser `rule_parse`:

- `yes / y / confirm / go ahead / ok` → `confirm`; `no / cancel / stop` → `decline`.
- Account IDs are found with the pattern `ACC-dddd` / `EXT-dddd`; they are removed before looking for an amount so that `ACC-2001` is never read as $2,001.
- Amounts: `$1,500`, `$200.50`, `300 dollars`.
- `transfer / send / wire / pay / move` → `transfer`; `from <ID|checking|savings>` gives the source, `to <ID>` (or the last account ID) gives the destination; words like `skip`, `bypass`, `without the security check` set `skip_review`.
- `transactions / history / statement / activity / spent` → `view_transactions`; `balance / how much` → `check_balance`; `help` → `help`; anything else → `unknown`.

## Decision logic (routing)

| Situation | What the Concierge does |
|---|---|
| No session yet | Sends `authenticate {customer_id, pin}` to **AuthAgent**. If the reply is not `verified`, it answers with a refusal (and attempts left / locked notice) and stops. Otherwise it stores the session token. |
| `check_balance` / `view_transactions` | Sends `get_balance` / `get_transactions {session_token, account_id, account_type}` to **AccountAgent** and formats the result. |
| `transfer` | If no source account was named, asks **AccountAgent** `list_my_accounts` and picks the named type (default checking). Sends `assess_transfer {customer_id, from_account, to_account, amount}` to **RiskAgent**. `deny` → explains why. `confirmation_required` → stores the reference and asks the customer to reply YES/NO. `approve` → sends `execute_transfer {session_token, from_account, to_account, amount, approval_id}` to **AccountAgent**. |
| `confirm` / `decline` | Sends `confirm_transfer {ref, customer_confirmed}` to **RiskAgent**; if approved, sends `execute_transfer` to **AccountAgent**. |
| Any new request while a transfer is pending | Drops the pending transfer (P9). |
| `help` / `unknown` | Answers directly without contacting other agents. |

It reports "Done. Sent …" only when AccountAgent returns `status: completed` (P14).

**Phase 1 gap (P8, P9).** If `skip_review` is true, the Concierge uses an "express" path left over from early development and sends `execute_transfer` straight to AccountAgent with `approval_id = null`, without contacting RiskAgent. See episode 6. Phase 2 removes this path.
