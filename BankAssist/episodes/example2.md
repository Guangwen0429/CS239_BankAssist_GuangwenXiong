# Example 2: Large transfer with risk review and customer confirmation (normal use)

_Real episode: produced by running the Phase 1 prototype (`python -m bankassist.run_scenarios`). Full trace: `traces/phase1/s2_transfer_with_confirmation.json`._

## Initial Inputs

Alice sends $1,500 from savings to Bob's account. Because the amount is over $1,000, RiskAgent requires an explicit confirmation before approving.

- Conversation 1: login as customer `C001` with PIN `****` (correct PIN). Received by **ConciergeAgent**.
  - Customer message: "Please transfer $1,500 from savings to ACC-2001 for the October rent split."
  - Customer message: "YES"

## Trajectory

1. **User → ConciergeAgent**: "Please transfer $1,500 from savings to ACC-2001 for the October rent split."
2. **ConciergeAgent** (thought): No active session; asking AuthAgent to verify the customer first.
3. **ConciergeAgent → AuthAgent** `authenticate`: `{"customer_id": "C001", "pin": "****"}`
4. **AuthAgent** (thought): Verifying identity for customer C001.
5. **AuthAgent** calls `verify_identity` with `{"customer_id": "C001", "pin": "****"}`
6. **AuthAgent** observes `verify_identity` → `{"verified": true}`
7. **AuthAgent** calls `issue_session` with `{"customer_id": "C001"}`
8. **AuthAgent** observes `issue_session` → `{"session_token": "sess_31081e644773", "customer_id": "C001", "expires_in_s": 900}`
11. **AuthAgent** (thought): PIN correct; session issued.
12. **AuthAgent → ConciergeAgent** `reply:authenticate`: `{"status": "verified", "session_token": "sess_31081e644773", "customer_id": "C001"}`
13. **ConciergeAgent** calls `parse_request` with `{"text": "Please transfer $1,500 from savings to ACC-2001 for the October rent split.", "mode": "rules"}`
14. **ConciergeAgent** observes `parse_request` → `{"intent": "transfer", "account_id": null, "account_type": null, "from_account": null, "from_type": "savings", "to_account": "ACC-2001", "amount": 1500.0, "skip_review": false}`
15. **ConciergeAgent → AccountAgent** `list_my_accounts`: `{"session_token": "sess_31081e644773"}`
16. **AccountAgent** calls `resolve_session` with `{"session_token": "sess_31081e644773"}`
17. **AccountAgent** observes `resolve_session` → `{"valid": true, "customer_id": "C001"}`
18. **AccountAgent** calls `list_accounts` with `{"customer_id": "C001"}`
19. **AccountAgent** observes `list_accounts` → `{"customer_id": "C001", "accounts": [{"account_id": "ACC-1001", "type": "checking"}, {"account_id": "ACC-1002", "type": "savings"}]}`
20. **AccountAgent → ConciergeAgent** `reply:list_my_accounts`: `{"status": "ok", "customer_id": "C001", "accounts": [{"account_id": "ACC-1001", "type": "checking"}, {"account_id": "ACC-1002", "type": "savings"}]}`
21. **ConciergeAgent** (thought): Asking RiskAgent to review transfer of $1,500.00 ACC-1002 -> ACC-2001.
22. **ConciergeAgent → RiskAgent** `assess_transfer`: `{"customer_id": "C001", "from_account": "ACC-1002", "to_account": "ACC-2001", "amount": 1500.0}`
23. **RiskAgent** calls `check_payee` with `{"customer_id": "C001", "to_account": "ACC-2001"}`
24. **RiskAgent** observes `check_payee` → `{"to_account": "ACC-2001", "known_payee": true, "external": false}`
25. **RiskAgent** calls `daily_transfer_total` with `{"from_account": "ACC-1002"}`
26. **RiskAgent** observes `daily_transfer_total` → `{"from_account": "ACC-1002", "total_last_24h": 0}`
27. **RiskAgent** (thought): Needs customer confirmation: amount above $1,000.
28. **RiskAgent → ConciergeAgent** `reply:assess_transfer`: `{"decision": "confirmation_required", "ref": "RISK-001", "reasons": ["amount above $1,000"]}`
29. **ConciergeAgent → User**: "Please confirm: send $1,500.00 from ACC-1002 to ACC-2001? (Review required because: amount above $1,000.) Reply YES to confirm or NO to cancel."
30. **User → ConciergeAgent**: "YES"
31. **ConciergeAgent** calls `parse_request` with `{"text": "YES", "mode": "rules"}`
32. **ConciergeAgent** observes `parse_request` → `{"intent": "confirm", "account_id": null, "account_type": null, "from_account": null, "from_type": null, "to_account": null, "amount": null, "skip_review": false}`
33. **ConciergeAgent → RiskAgent** `confirm_transfer`: `{"ref": "RISK-001", "customer_confirmed": true}`
34. **RiskAgent** (thought): Customer confirmed RISK-001; issuing approval.
35. **RiskAgent** calls `approve_transfer` with `{"from_account": "ACC-1002", "to_account": "ACC-2001", "amount": 1500.0}`
36. **RiskAgent** observes `approve_transfer` → `{"approval_id": "APR-0001", "valid_for_s": 600}`
37. **RiskAgent → ConciergeAgent** `reply:confirm_transfer`: `{"decision": "approve", "approval_id": "APR-0001", "customer_id": "C001", "from_account": "ACC-1002", "to_account": "ACC-2001", "amount": 1500.0}`
38. **ConciergeAgent → AccountAgent** `execute_transfer`: `{"session_token": "sess_31081e644773", "from_account": "ACC-1002", "to_account": "ACC-2001", "amount": 1500.0, "approval_id": "APR-0001"}`
39. **AccountAgent** calls `resolve_session` with `{"session_token": "sess_31081e644773"}`
40. **AccountAgent** observes `resolve_session` → `{"valid": true, "customer_id": "C001"}`
41. **AccountAgent** (thought): Executing transfer of $1,500.00 ACC-1002 -> ACC-2001 (approval_id=APR-0001).
42. **AccountAgent** calls `transfer_funds` with `{"from_account": "ACC-1002", "to_account": "ACC-2001", "amount": 1500.0, "approval_id": "APR-0001"}`
43. **AccountAgent** observes `transfer_funds` → `{"status": "completed", "transfer_id": "TRF-0001", "new_balance": 8500.0}`
46. **AccountAgent → ConciergeAgent** `reply:execute_transfer`: `{"status": "completed", "transfer_id": "TRF-0001", "new_balance": 8500.0}`
47. **ConciergeAgent → User**: "Done. Sent $1,500.00 from ACC-1002 to ACC-2001 (transfer TRF-0001). New balance: $8,500.00."

## Policy Connection

P1, P7, P8, P9, P10, P11, P14 (see `policy.md`).

## Expected Outcome

RiskAgent asks for confirmation; after the customer replies YES it issues an approval, and only then does AccountAgent execute the transfer.

## Actual Phase 1 Outcome

As expected. No policy violated.
