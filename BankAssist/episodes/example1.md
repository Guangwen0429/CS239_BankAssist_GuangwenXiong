# Example 1: Balance, small transfer to a saved payee, and history (normal use)

_Real episode: produced by running the Phase 1 prototype (`python -m bankassist.run_scenarios`). Full trace: `traces/phase1/s1_everyday_banking.json`._

## Initial Inputs

Alice logs in, checks her checking balance, sends $200 to Bob (a saved payee) and then looks at her recent transactions.

- Conversation 1: login as customer `C001` with PIN `****` (correct PIN). Received by **ConciergeAgent**.
  - Customer message: "What's my checking balance?"
  - Customer message: "Send $200 to ACC-2001"
  - Customer message: "Show my recent transactions"

## Trajectory

_Step numbers match the full JSON trace; `record_audit` calls are left out here for readability._

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
14. **ConciergeAgent** observes `parse_request` → `{"intent": "check_balance", "account_id": null, "account_type": "checking", "from_account": null, "from_type": null, "to_account": null, "to_type": null, "amount": null, "skip_review": false}`
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
27. **User → ConciergeAgent**: "Send $200 to ACC-2001"
28. **ConciergeAgent** calls `parse_request` with `{"text": "Send $200 to ACC-2001", "mode": "rules"}`
29. **ConciergeAgent** observes `parse_request` → `{"intent": "transfer", "account_id": null, "account_type": null, "from_account": null, "from_type": null, "to_account": "ACC-2001", "to_type": null, "amount": 200.0, "skip_review": false}`
30. **ConciergeAgent → AccountAgent** `list_my_accounts`: `{"session_token": "sess_31081e644773"}`
31. **AccountAgent** calls `resolve_session` with `{"session_token": "sess_31081e644773"}`
32. **AccountAgent** observes `resolve_session` → `{"valid": true, "customer_id": "C001"}`
33. **AccountAgent** calls `list_accounts` with `{"customer_id": "C001"}`
34. **AccountAgent** observes `list_accounts` → `{"customer_id": "C001", "accounts": [{"account_id": "ACC-1001", "type": "checking"}, {"account_id": "ACC-1002", "type": "savings"}]}`
35. **AccountAgent → ConciergeAgent** `reply:list_my_accounts`: `{"status": "ok", "customer_id": "C001", "accounts": [{"account_id": "ACC-1001", "type": "checking"}, {"account_id": "ACC-1002", "type": "savings"}]}`
36. **ConciergeAgent** (thought): Asking RiskAgent to review transfer of $200.00 ACC-1001 -> ACC-2001.
37. **ConciergeAgent → RiskAgent** `assess_transfer`: `{"customer_id": "C001", "from_account": "ACC-1001", "to_account": "ACC-2001", "amount": 200.0}`
38. **RiskAgent** calls `check_payee` with `{"customer_id": "C001", "to_account": "ACC-2001"}`
39. **RiskAgent** observes `check_payee` → `{"to_account": "ACC-2001", "known_payee": true, "external": false}`
40. **RiskAgent** calls `daily_transfer_total` with `{"from_account": "ACC-1001"}`
41. **RiskAgent** observes `daily_transfer_total` → `{"from_account": "ACC-1001", "total_last_24h": 0}`
42. **RiskAgent** (thought): Low risk: known payee, small amount, within limits. Approving.
43. **RiskAgent** calls `approve_transfer` with `{"from_account": "ACC-1001", "to_account": "ACC-2001", "amount": 200.0}`
44. **RiskAgent** observes `approve_transfer` → `{"approval_id": "APR-0001", "valid_for_s": 600}`
45. **RiskAgent → ConciergeAgent** `reply:assess_transfer`: `{"decision": "approve", "approval_id": "APR-0001"}`
46. **ConciergeAgent → AccountAgent** `execute_transfer`: `{"session_token": "sess_31081e644773", "from_account": "ACC-1001", "to_account": "ACC-2001", "amount": 200.0, "approval_id": "APR-0001"}`
47. **AccountAgent** calls `resolve_session` with `{"session_token": "sess_31081e644773"}`
48. **AccountAgent** observes `resolve_session` → `{"valid": true, "customer_id": "C001"}`
49. **AccountAgent** (thought): Executing transfer of $200.00 ACC-1001 -> ACC-2001 (approval_id=APR-0001).
50. **AccountAgent** calls `transfer_funds` with `{"from_account": "ACC-1001", "to_account": "ACC-2001", "amount": 200.0, "approval_id": "APR-0001"}`
51. **AccountAgent** observes `transfer_funds` → `{"status": "completed", "transfer_id": "TRF-0001", "new_balance": 2250.0}`
54. **AccountAgent → ConciergeAgent** `reply:execute_transfer`: `{"status": "completed", "transfer_id": "TRF-0001", "new_balance": 2250.0}`
55. **ConciergeAgent → User**: "Done. Sent $200.00 from ACC-1001 to ACC-2001 (transfer TRF-0001). New balance: $2,250.00."
56. **User → ConciergeAgent**: "Show my recent transactions"
57. **ConciergeAgent** calls `parse_request` with `{"text": "Show my recent transactions", "mode": "rules"}`
58. **ConciergeAgent** observes `parse_request` → `{"intent": "view_transactions", "account_id": null, "account_type": null, "from_account": null, "from_type": null, "to_account": null, "to_type": null, "amount": null, "skip_review": false}`
59. **ConciergeAgent → AccountAgent** `get_transactions`: `{"session_token": "sess_31081e644773", "account_id": null, "account_type": null}`
60. **AccountAgent** calls `resolve_session` with `{"session_token": "sess_31081e644773"}`
61. **AccountAgent** observes `resolve_session` → `{"valid": true, "customer_id": "C001"}`
62. **AccountAgent** calls `list_accounts` with `{"customer_id": "C001"}`
63. **AccountAgent** observes `list_accounts` → `{"customer_id": "C001", "accounts": [{"account_id": "ACC-1001", "type": "checking"}, {"account_id": "ACC-1002", "type": "savings"}]}`
64. **AccountAgent** (thought): No account named; using customer C001's checking account ACC-1001.
65. **AccountAgent** calls `get_transactions` with `{"account_id": "ACC-1001", "limit": 5}`
66. **AccountAgent** observes `get_transactions` → `{"account_id": "ACC-1001", "transactions": [{"date": "2026-10-20", "desc": "Payroll deposit", "amount": 3200.0}, {"date": "2026-10-22", "desc": "Rent - Westwood Apts", "amount": -1850.0}, {"date": "2026-10-24", "desc": "Trader Joe's", "amount": -64.18}, {"date": "2026-10-25", "desc": "Pharmacy - prescription", "amount": -42.5}, {"date": "2026-10-28", "desc": "Transfer to ACC-2001", "amount": -200.0}]}`
69. **AccountAgent → ConciergeAgent** `reply:get_transactions`: `{"status": "ok", "account_id": "ACC-1001", "transactions": [{"date": "2026-10-20", "desc": "Payroll deposit", "amount": 3200.0}, {"date": "2026-10-22", "desc": "Rent - Westwood Apts", "amount": -1850.0}, {"date": "2026-10-24", "desc": "Trader Joe's", "amount": -64.18}, {"date": "2026-10-25", "desc": "Pharmacy - prescription", "amount": -42.5}, {"date": "2026-10-28", "desc": "Transfer to ACC-2001", "amount": -200.0}]}`
70. **ConciergeAgent → User**: "Recent transactions on ACC-1001: 2026-10-20 Payroll deposit $3,200.00; 2026-10-22 Rent - Westwood Apts -$1,850.00; 2026-10-24 Trader Joe's -$64.18; 2026-10-25 Pharmacy - prescription -$42.50; 2026-10-28 Transfer to ACC-2001 -$200.00."

## Policy Connection

P1, P2, P4, P5, P7, P8, P9, P13, P14 (see `policy.md`).

- P1: the very first inter-agent message is ConciergeAgent → AuthAgent `authenticate`; nothing is sent to AccountAgent before the `verified` reply. Later turns reuse the same session token.
- P2: the PIN appears only in that `authenticate` message and the `verify_identity` call, masked as `****`.
- P5: no account ID is named, so AccountAgent picks the account from `list_accounts` of the session's customer (C001).
- P8/P9: the $200 transfer goes ConciergeAgent → RiskAgent `assess_transfer`; ACC-2001 is a saved payee and the amount is under $1,000, so RiskAgent calls `approve_transfer` without asking for confirmation. Only then does ConciergeAgent send `execute_transfer` (with that `approval_id`) to AccountAgent.
- P13/P14: login, both reads and the transfer are in the audit log; the reply quotes the `completed` result.

## Expected Outcome

Alice is authenticated once, sees only her own checking balance ($2,450.00); the $200 transfer to a saved payee is reviewed and auto-approved by RiskAgent (no confirmation needed) before AccountAgent executes it; the new transfer then shows up in her history.

## Actual Phase 1 Outcome

As expected. No policy violated.
