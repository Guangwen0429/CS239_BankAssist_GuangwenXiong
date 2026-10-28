# AccountAgent

**Kind:** Rule-based. Implementation: `AccountAgent` in `src/bankassist/agents.py`.

**Available tools:** `resolve_session`, `list_accounts`, `get_balance`, `get_transactions`, `transfer_funds`, `record_audit`.

**Role.** The only agent with access to account data and the only agent that can move money (P7).

## Implementation / decision logic

For every request it first calls `resolve_session(session_token)`. If the token is missing, unknown or expired it replies `{status: "error", reason: "invalid_session"}` and does nothing else (P1). Otherwise the session gives the customer ID.

- **`list_my_accounts {session_token}`**: `list_accounts(customer_id)` and returns the list.
- **`get_balance` / `get_transactions {session_token, account_id?, account_type?}`**
  - If `account_id` is given, it is used as-is.
  - Otherwise it calls `list_accounts(customer_id)` and picks the customer's account of the requested type (default checking).
  - Calls `get_balance(account_id)` or `get_transactions(account_id, limit=5)`, writes an audit entry, and returns the result.
- **`execute_transfer {session_token, from_account, to_account, amount, approval_id}`**
  - Calls `transfer_funds(...)`. The tool refuses unknown accounts, non-positive amounts and overdrafts (P10).
  - Writes a `transfer` audit entry (including the approval ID and status) and returns the tool result.

**Phase 1 gaps.**

- *P5/P6:* when `account_id` (or `from_account`) is given, the agent does not check that the account belongs to the session's customer, so a logged-in customer can read another customer's account by naming its ID (episode 5).
- *P8:* `approval_id` is passed through to `transfer_funds` but is not validated (existence, matching from/to/amount, unused, age), so a transfer with `approval_id = null` is executed (episode 6).

Phase 2 adds both checks.
