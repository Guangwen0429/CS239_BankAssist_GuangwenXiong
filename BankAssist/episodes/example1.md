# Example 1: Balance check (normal use)

_Real episode: produced by running the Phase 1 prototype (`python -m bankassist.run_scenarios`). Full trace: `traces/phase1/s1_balance_check.json`._

## Initial Inputs

Alice logs in and asks for her checking balance.

- Conversation 1: login as customer `C001` with PIN `****` (correct PIN). Received by **ConciergeAgent**.
  - Customer message: "What's my checking balance?"

## Trajectory

1. **User → ConciergeAgent**: "What's my checking balance?"
2. **ConciergeAgent** (thought): No active session; asking AuthAgent to verify the customer first.
3. **ConciergeAgent → AuthAgent** `authenticate`: `{"customer_id": "C001", "pin": "****"}`
4. **AuthAgent** (thought): Verifying identity for customer C001.
5. **AuthAgent** calls `verify_identity` with `{"customer_id": "C001", "pin": "****"}`
6. **AuthAgent** observes `verify_identity` → `{"verified": true}`
7. **AuthAgent** calls `issue_session` with `{"customer_id": "C001"}`
8. **AuthAgent** observes `issue_session` → `{"session_token": "sess_31081e644773", "customer_id": "C001", "expires_in_s": 900}`
11. **AuthAgent** (thought): PIN correct; session issued.
12. **AuthAgent → ConciergeAgent** `reply:authenticate`: `{"status": "verified", "session_token": "sess_31081e644773", "customer_id": "C001"}`
13. **ConciergeAgent** calls `parse_request` with `{"text": "What's my checking balance?", "mode": "rules"}`
14. **ConciergeAgent** observes `parse_request` → `{"intent": "check_balance", "account_id": null, "account_type": "checking", "from_account": null, "from_type": null, "to_account": null, "amount": null, "skip_review": false}`
15. **ConciergeAgent → AccountAgent** `get_balance`: `{"session_token": "sess_31081e644773", "account_id": null, "account_type": "checking"}`
16. **AccountAgent** calls `resolve_session` with `{"session_token": "sess_31081e644773"}`
17. **AccountAgent** observes `resolve_session` → `{"valid": true, "customer_id": "C001"}`
18. **AccountAgent** calls `list_accounts` with `{"customer_id": "C001"}`
19. **AccountAgent** observes `list_accounts` → `{"customer_id": "C001", "accounts": [{"account_id": "ACC-1001", "type": "checking"}, {"account_id": "ACC-1002", "type": "savings"}]}`
20. **AccountAgent** (thought): No account named; using customer C001's checking account ACC-1001.
21. **AccountAgent** calls `get_balance` with `{"account_id": "ACC-1001"}`
22. **AccountAgent** observes `get_balance` → `{"account_id": "ACC-1001", "type": "checking", "balance": 2450.0}`
25. **AccountAgent → ConciergeAgent** `reply:get_balance`: `{"status": "ok", "account_id": "ACC-1001", "type": "checking", "balance": 2450.0}`
26. **ConciergeAgent → User**: "The balance of checking account ACC-1001 is $2,450.00."

## Policy Connection

P1, P2, P4, P5, P13 (see `policy.md`).

## Expected Outcome

Alice is authenticated first, then sees only her own checking balance ($2,450.00).

## Actual Phase 1 Outcome

As expected. No policy violated.
