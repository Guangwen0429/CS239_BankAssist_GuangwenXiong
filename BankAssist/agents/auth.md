# AuthAgent

**Kind:** Rule-based. Implementation: `AuthAgent` in `src/bankassist/agents.py`.

**Available tools:** `verify_identity`, `issue_session`, `resolve_session`, `record_audit`.

**Role.** Owns customer authentication and sessions. It is the only agent that ever receives a PIN.

## Implementation / decision logic

Requests it accepts (from the ConciergeAgent):

- **`authenticate {customer_id, pin}`**
  1. Calls `verify_identity(customer_id, pin)`. The tool compares the PIN with the stored PIN, counts consecutive failures and locks the profile on the 3rd failure (P3).
  2. If verified: calls `issue_session(customer_id)` to create a session token (valid 15 minutes), writes a `login_success` audit entry, and replies `{status: "verified", session_token, customer_id}`.
  3. If not verified: writes a `login_failed` audit entry with the reason (never the PIN, P13) and replies `{status: "failed", reason, attempts_left?}`, where reason is `unknown_customer`, `wrong_pin` or `locked`.
- **`validate_session {session_token}`**: calls `resolve_session` and returns `{valid, customer_id?}`.
- Anything else → `{status: "error", reason: "unsupported request"}`.

There is no randomness or LLM involved: the same inputs always give the same decision. PINs are masked as `****` in traces (P2).
