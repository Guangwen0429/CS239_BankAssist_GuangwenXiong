# Trace `s1_balance_check`: Balance check (normal use)

Alice logs in and asks for her checking balance.

- **concierge_mode:** rules
- **policies:** P1, P2, P4, P5, P13
- **expected:** Alice is authenticated first, then sees only her own checking balance ($2,450.00).
- **phase1_result:** As expected. No policy violated.

| # | Agent | Kind | Detail |
|---|---|---|---|
| 1 | User | user_input | → ConciergeAgent: "What's my checking balance?" |
| 2 | ConciergeAgent | thought | _No active session; asking AuthAgent to verify the customer first._ |
| 3 | ConciergeAgent | message | → **AuthAgent** [authenticate] `{"customer_id": "C001", "pin": "****"}` |
| 4 | AuthAgent | thought | _Verifying identity for customer C001._ |
| 5 | AuthAgent | action | `verify_identity({"customer_id": "C001", "pin": "****"})` |
| 6 | AuthAgent | observation | `verify_identity` → `{"verified": true}` |
| 7 | AuthAgent | action | `issue_session({"customer_id": "C001"})` |
| 8 | AuthAgent | observation | `issue_session` → `{"session_token": "sess_31081e644773", "customer_id": "C001", "expires_in_s": 900}` |
| 9 | AuthAgent | action | `record_audit({"agent": "AuthAgent", "event": "login_success", "details": {"customer_id": "C001"}})` |
| 10 | AuthAgent | observation | `record_audit` → `{"logged": true, "seq": 1}` |
| 11 | AuthAgent | thought | _PIN correct; session issued._ |
| 12 | AuthAgent | message | → **ConciergeAgent** [reply:authenticate] `{"status": "verified", "session_token": "sess_31081e644773", "customer_id": "C001"}` |
| 13 | ConciergeAgent | action | `parse_request({"text": "What's my checking balance?", "mode": "rules"})` |
| 14 | ConciergeAgent | observation | `parse_request` → `{"intent": "check_balance", "account_id": null, "account_type": "checking", "from_account": null, "from_type": null, "to_account": null, "amount": null, "skip_review": false}` |
| 15 | ConciergeAgent | message | → **AccountAgent** [get_balance] `{"session_token": "sess_31081e644773", "account_id": null, "account_type": "checking"}` |
| 16 | AccountAgent | action | `resolve_session({"session_token": "sess_31081e644773"})` |
| 17 | AccountAgent | observation | `resolve_session` → `{"valid": true, "customer_id": "C001"}` |
| 18 | AccountAgent | action | `list_accounts({"customer_id": "C001"})` |
| 19 | AccountAgent | observation | `list_accounts` → `{"customer_id": "C001", "accounts": [{"account_id": "ACC-1001", "type": "checking"}, {"account_id": "ACC-1002", "type": "savings"}]}` |
| 20 | AccountAgent | thought | _No account named; using customer C001's checking account ACC-1001._ |
| 21 | AccountAgent | action | `get_balance({"account_id": "ACC-1001"})` |
| 22 | AccountAgent | observation | `get_balance` → `{"account_id": "ACC-1001", "type": "checking", "balance": 2450.0}` |
| 23 | AccountAgent | action | `record_audit({"agent": "AccountAgent", "event": "get_balance", "details": {"customer_id": "C001", "account_id": "ACC-1001"}})` |
| 24 | AccountAgent | observation | `record_audit` → `{"logged": true, "seq": 2}` |
| 25 | AccountAgent | message | → **ConciergeAgent** [reply:get_balance] `{"status": "ok", "account_id": "ACC-1001", "type": "checking", "balance": 2450.0}` |
| 26 | ConciergeAgent | response | → User: "The balance of checking account ACC-1001 is $2,450.00." |

## Audit log at end of run

| seq | agent | event | details |
|---|---|---|---|
| 1 | AuthAgent | login_success | `{"customer_id": "C001"}` |
| 2 | AccountAgent | get_balance | `{"customer_id": "C001", "account_id": "ACC-1001"}` |
