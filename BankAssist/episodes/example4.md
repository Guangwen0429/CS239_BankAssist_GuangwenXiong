# Example 4: Transfer above the single-transfer limit is denied

_Real episode: produced by running the Phase 1 prototype (`python3 -m bankassist.run_scenarios`). Full trace: `traces/phase1/s4_transfer_over_limit.json`._

## Initial Inputs

Carol tries to send $6,000, which is above the $5,000 single-transfer limit.

- Conversation 1: login as customer `C003` with PIN `****` (correct PIN). Received by **ConciergeAgent**.
  - Customer message: "Send $6,000 to ACC-1001"

## Trajectory

_Step numbers match the full JSON trace; `record_audit` calls are left out here for readability._

1. **User → ConciergeAgent**: "Send $6,000 to ACC-1001"
2. **ConciergeAgent** (thought): No active session; asking AuthAgent to verify the customer first.
3. **ConciergeAgent → AuthAgent** `authenticate`: `{"customer_id": "C003", "pin": "****"}`
4. **AuthAgent** (thought): ConciergeAgent asks me to verify customer C003. I check the PIN with verify_identity; a session is issued only if it is correct (P1).
5. **AuthAgent** calls `verify_identity` with `{"customer_id": "C003", "pin": "****"}`
6. **AuthAgent** observes `verify_identity` → `{"verified": true}`
7. **AuthAgent** calls `issue_session` with `{"customer_id": "C003"}`
8. **AuthAgent** observes `issue_session` → `{"session_token": "sess_31081e644773", "customer_id": "C003", "expires_in_s": 900}`
11. **AuthAgent** (thought): PIN correct. Session issued (valid 15 minutes); I reply with the token only, never the PIN (P16).
12. **AuthAgent → ConciergeAgent** `reply:authenticate`: `{"status": "verified", "session_token": "sess_31081e644773", "customer_id": "C003"}`
13. **ConciergeAgent** calls `parse_request` with `{"text": "Send $6,000 to ACC-1001", "mode": "rules"}`
14. **ConciergeAgent** observes `parse_request` → `{"intent": "transfer", "account_id": null, "account_type": null, "from_account": null, "from_type": null, "to_account": "ACC-1001", "to_type": null, "amount": 6000.0, "skip_review": false}`
15. **ConciergeAgent** (thought): The customer wants to send $6,000.00 from their default account to ACC-1001. Plan: resolve the accounts, have RiskAgent review it, and execute only with RiskAgent's approval (P8).
16. **ConciergeAgent → AccountAgent** `list_my_accounts`: `{"session_token": "sess_31081e644773"}`
17. **AccountAgent** calls `resolve_session` with `{"session_token": "sess_31081e644773"}`
18. **AccountAgent** observes `resolve_session` → `{"valid": true, "customer_id": "C003"}`
19. **AccountAgent** (thought): ConciergeAgent sent list_my_accounts; the session belongs to customer C003.
20. **AccountAgent** calls `list_accounts` with `{"customer_id": "C003"}`
21. **AccountAgent** observes `list_accounts` → `{"customer_id": "C003", "accounts": [{"account_id": "ACC-3001", "type": "checking"}]}`
22. **AccountAgent → ConciergeAgent** `reply:list_my_accounts`: `{"status": "ok", "customer_id": "C003", "accounts": [{"account_id": "ACC-3001", "type": "checking"}]}`
23. **ConciergeAgent** (thought): Asking RiskAgent to review transfer of $6,000.00 ACC-3001 -> ACC-1001. RiskAgent gets only the customer ID, the two accounts and the amount (P11).
24. **ConciergeAgent → RiskAgent** `assess_transfer`: `{"customer_id": "C003", "from_account": "ACC-3001", "to_account": "ACC-1001", "amount": 6000.0}`
25. **RiskAgent** calls `check_payee` with `{"customer_id": "C003", "to_account": "ACC-1001"}`
26. **RiskAgent** observes `check_payee` → `{"to_account": "ACC-1001", "known_payee": false, "external": false}`
27. **RiskAgent** calls `daily_transfer_total` with `{"from_account": "ACC-3001"}`
28. **RiskAgent** observes `daily_transfer_total` → `{"from_account": "ACC-3001", "total_last_24h": 0}`
29. **RiskAgent** (thought): Reviewing $6,000.00 ACC-3001 -> ACC-1001 for C003. Single-transfer limit: FAILS ($6,000.00 vs $5,000). 24h total: ok ($0.00 already sent). Size: large, needs confirmation. Payee: new.
30. **RiskAgent** (thought): Hard limit hit: amount exceeds single-transfer limit $5,000. Denying; no approval (P10).
33. **RiskAgent → ConciergeAgent** `reply:assess_transfer`: `{"decision": "deny", "reasons": ["amount exceeds single-transfer limit $5,000"]}`
34. **ConciergeAgent → User**: "I can't make this transfer: amount exceeds single-transfer limit $5,000. No money was moved."

## Policy Connection

P8, P10, P14 (see `policy.md`).

- P10: RiskAgent's rules deny the $6,000 request (single-transfer limit $5,000) and audit it as `transfer_denied`.
- P8: because there is no approval, the ConciergeAgent never sends `execute_transfer`; AccountAgent never calls `transfer_funds`.
- P14: the customer is told the transfer cannot be made.

## Expected Outcome

RiskAgent denies the transfer; AccountAgent is never asked to move money.

## Actual Phase 1 Outcome

As expected. No policy violated.
