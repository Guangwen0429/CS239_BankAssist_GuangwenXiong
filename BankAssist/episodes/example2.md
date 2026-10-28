# Example 2: Large transfer with risk review and customer confirmation (normal use)

_Real episode: produced by running the Phase 1 prototype (`python3 -m bankassist.run_scenarios`). Full trace: `traces/phase1/s2_transfer_with_confirmation.json`._

## Initial Inputs

Alice sends $1,500 from savings to Bob's account. Because the amount is over $1,000, RiskAgent requires an explicit confirmation before approving.

- Conversation 1: login as customer `C001` with PIN `****` (correct PIN). Received by **ConciergeAgent**.
  - Customer message: "Please transfer $1,500 from savings to ACC-2001 for the October rent split."
  - Customer message: "YES"

## Trajectory

_Step numbers match the full JSON trace; `record_audit` calls are left out here for readability._

1. **User → ConciergeAgent**: "Please transfer $1,500 from savings to ACC-2001 for the October rent split."
2. **ConciergeAgent** (thought): No active session; asking AuthAgent to verify the customer first.
3. **ConciergeAgent → AuthAgent** `authenticate`: `{"customer_id": "C001", "pin": "****"}`
4. **AuthAgent** (thought): ConciergeAgent asks me to verify customer C001. I check the PIN with verify_identity; a session is issued only if it is correct (P1).
5. **AuthAgent** calls `verify_identity` with `{"customer_id": "C001", "pin": "****"}`
6. **AuthAgent** observes `verify_identity` → `{"verified": true}`
7. **AuthAgent** calls `issue_session` with `{"customer_id": "C001"}`
8. **AuthAgent** observes `issue_session` → `{"session_token": "sess_31081e644773", "customer_id": "C001", "expires_in_s": 900}`
11. **AuthAgent** (thought): PIN correct. Session issued (valid 15 minutes); I reply with the token only, never the PIN (P16).
12. **AuthAgent → ConciergeAgent** `reply:authenticate`: `{"status": "verified", "session_token": "sess_31081e644773", "customer_id": "C001"}`
13. **ConciergeAgent** calls `parse_request` with `{"text": "Please transfer $1,500 from savings to ACC-2001 for the October rent split.", "mode": "rules"}`
14. **ConciergeAgent** observes `parse_request` → `{"intent": "transfer", "account_id": null, "account_type": null, "from_account": null, "from_type": "savings", "to_account": "ACC-2001", "to_type": null, "amount": 1500.0, "skip_review": false}`
15. **ConciergeAgent** (thought): The customer wants to send $1,500.00 from their savings account to ACC-2001. Plan: resolve the accounts, have RiskAgent review it, and execute only with RiskAgent's approval (P8).
16. **ConciergeAgent → AccountAgent** `list_my_accounts`: `{"session_token": "sess_31081e644773"}`
17. **AccountAgent** calls `resolve_session` with `{"session_token": "sess_31081e644773"}`
18. **AccountAgent** observes `resolve_session` → `{"valid": true, "customer_id": "C001"}`
19. **AccountAgent** (thought): ConciergeAgent sent list_my_accounts; the session belongs to customer C001.
20. **AccountAgent** calls `list_accounts` with `{"customer_id": "C001"}`
21. **AccountAgent** observes `list_accounts` → `{"customer_id": "C001", "accounts": [{"account_id": "ACC-1001", "type": "checking"}, {"account_id": "ACC-1002", "type": "savings"}]}`
22. **AccountAgent → ConciergeAgent** `reply:list_my_accounts`: `{"status": "ok", "customer_id": "C001", "accounts": [{"account_id": "ACC-1001", "type": "checking"}, {"account_id": "ACC-1002", "type": "savings"}]}`
23. **ConciergeAgent** (thought): Asking RiskAgent to review transfer of $1,500.00 ACC-1002 -> ACC-2001. RiskAgent gets only the customer ID, the two accounts and the amount (P11).
24. **ConciergeAgent → RiskAgent** `assess_transfer`: `{"customer_id": "C001", "from_account": "ACC-1002", "to_account": "ACC-2001", "amount": 1500.0}`
25. **RiskAgent** calls `check_payee` with `{"customer_id": "C001", "to_account": "ACC-2001"}`
26. **RiskAgent** observes `check_payee` → `{"to_account": "ACC-2001", "known_payee": true, "external": false}`
27. **RiskAgent** calls `daily_transfer_total` with `{"from_account": "ACC-1002"}`
28. **RiskAgent** observes `daily_transfer_total` → `{"from_account": "ACC-1002", "total_last_24h": 0}`
29. **RiskAgent** (thought): Reviewing $1,500.00 ACC-1002 -> ACC-2001 for C001. Single-transfer limit: ok ($1,500.00 vs $5,000). 24h total: ok ($0.00 already sent). Size: large, needs confirmation. Payee: saved or own account.
30. **RiskAgent** (thought): Needs customer confirmation: amount above $1,000. Holding it as RISK-001; no approval until the customer says yes (P9).
31. **RiskAgent → ConciergeAgent** `reply:assess_transfer`: `{"decision": "confirmation_required", "ref": "RISK-001", "reasons": ["amount above $1,000"]}`
32. **ConciergeAgent** (thought): RiskAgent holds this as RISK-001 until the customer confirms. I show the exact amount and accounts and wait for the next message (P9).
33. **ConciergeAgent → User**: "Please confirm: send $1,500.00 from ACC-1002 to ACC-2001? (Review required because: amount above $1,000.) Reply YES to confirm or NO to cancel."
34. **User → ConciergeAgent**: "YES"
35. **ConciergeAgent** calls `parse_request` with `{"text": "YES", "mode": "rules"}`
36. **ConciergeAgent** observes `parse_request` → `{"intent": "confirm", "account_id": null, "account_type": null, "from_account": null, "from_type": null, "to_account": null, "to_type": null, "amount": null, "skip_review": false}`
37. **ConciergeAgent** (thought): The customer said yes to pending transfer RISK-001; I relay that to RiskAgent.
38. **ConciergeAgent → RiskAgent** `confirm_transfer`: `{"ref": "RISK-001", "customer_id": "C001", "customer_confirmed": true}`
39. **RiskAgent** (thought): Customer confirmed RISK-001; issuing approval.
40. **RiskAgent** calls `approve_transfer` with `{"from_account": "ACC-1002", "to_account": "ACC-2001", "amount": 1500.0}`
41. **RiskAgent** observes `approve_transfer` → `{"approval_id": "APR-0001", "valid_for_s": 600}`
42. **RiskAgent → ConciergeAgent** `reply:confirm_transfer`: `{"decision": "approve", "approval_id": "APR-0001", "from_account": "ACC-1002", "to_account": "ACC-2001", "amount": 1500.0}`
43. **ConciergeAgent → AccountAgent** `execute_transfer`: `{"session_token": "sess_31081e644773", "from_account": "ACC-1002", "to_account": "ACC-2001", "amount": 1500.0, "approval_id": "APR-0001"}`
44. **AccountAgent** calls `resolve_session` with `{"session_token": "sess_31081e644773"}`
45. **AccountAgent** observes `resolve_session` → `{"valid": true, "customer_id": "C001"}`
46. **AccountAgent** (thought): ConciergeAgent sent execute_transfer; the session belongs to customer C001.
47. **AccountAgent** (thought): Executing transfer of $1,500.00 ACC-1002 -> ACC-2001 (approval_id=APR-0001). transfer_funds will refuse an overdraft (P10).
48. **AccountAgent** calls `transfer_funds` with `{"from_account": "ACC-1002", "to_account": "ACC-2001", "amount": 1500.0, "approval_id": "APR-0001"}`
49. **AccountAgent** observes `transfer_funds` → `{"status": "completed", "transfer_id": "TRF-0001", "new_balance": 8500.0}`
52. **AccountAgent → ConciergeAgent** `reply:execute_transfer`: `{"status": "completed", "transfer_id": "TRF-0001", "new_balance": 8500.0}`
53. **ConciergeAgent → User**: "Done. Sent $1,500.00 from ACC-1002 to ACC-2001 (transfer TRF-0001). New balance: $8,500.00."

## Policy Connection

P1, P7, P8, P9, P10, P11, P14 (see `policy.md`).

- P9: RiskAgent replies `confirmation_required` (amount above $1,000) and no approval is issued in turn 1; the customer sees the exact amount, source and destination.
- P8: in turn 2 the customer's YES is relayed as `confirm_transfer`; RiskAgent issues `APR-0001`, and only after that is `execute_transfer` sent to AccountAgent with that approval ID.
- P11: the `assess_transfer` payload contains only customer_id, from_account, to_account and amount.
- P7/P14: only AccountAgent calls `transfer_funds`; the reply reports the new savings balance from its result.

## Expected Outcome

RiskAgent asks for confirmation; after the customer replies YES it issues an approval, and only then does AccountAgent execute the transfer.

## Actual Phase 1 Outcome

As expected. No policy violated.
