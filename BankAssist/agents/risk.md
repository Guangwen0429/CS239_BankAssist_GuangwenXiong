# RiskAgent

**Kind:** Rule-based. Implementation: `RiskAgent` in `src/bankassist/agents.py`.

**Available tools:** `check_payee`, `daily_transfer_total`, `approve_transfer`, `record_audit`.

**Role.** Reviews every transfer before it can be executed and issues single-use approvals (P8). It never moves money itself (P7) and only sees the minimum transfer metadata (P11).

## Implementation / decision logic

- **`assess_transfer {customer_id, from_account, to_account, amount}`**
  1. `check_payee(customer_id, to_account)` → is the destination a saved payee? Is it external (`EXT-…`)?
  2. `daily_transfer_total(from_account)` → amount already sent from this account in the last 24h.
  3. Rules, checked in this order:
     - **Deny** if `amount > $5,000` or `daily total + amount > $10,000` (P10). Writes a `transfer_denied` audit entry and replies `{decision: "deny", reasons}`.
     - **Confirmation required** if `amount > $1,000`, or the payee is not saved, or the destination is external (P9). Stores the request under a reference such as `RISK-001` and replies `{decision: "confirmation_required", ref, reasons}`.
     - **Approve** otherwise: calls `approve_transfer(from, to, amount)` and replies `{decision: "approve", approval_id}`.
- **`confirm_transfer {ref, customer_confirmed}`**
  - Unknown reference → `deny`.
  - `customer_confirmed = false` → `{decision: "cancelled"}` and the pending request is discarded.
  - `customer_confirmed = true` → `approve_transfer(...)` for the stored from/to/amount and replies `{decision: "approve", approval_id, from_account, to_account, amount}`.

All thresholds are constants in `src/bankassist/bank.py` (`SINGLE_TRANSFER_LIMIT`, `DAILY_TRANSFER_LIMIT`, `STEP_UP_THRESHOLD`).
