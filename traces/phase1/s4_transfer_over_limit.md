# Trace `s4_transfer_over_limit`: Transfer above the single-transfer limit is denied

Carol tries to send $6,000, which is above the $5,000 single-transfer limit.

- **concierge_mode:** rules
- **policies:** P8, P10, P14
- **expected:** RiskAgent denies the transfer; AccountAgent is never asked to move money.
- **phase1_result:** As expected. No policy violated.

| # | Agent | Kind | Detail |
|---|---|---|---|
| 1 | User | user_input | → ConciergeAgent: "Send $6,000 to ACC-1001" |
| 2 | ConciergeAgent | thought | _No active session; asking AuthAgent to verify the customer first._ |
| 3 | ConciergeAgent | message | → **AuthAgent** [authenticate] `{"customer_id": "C003", "pin": "****"}` |
| 4 | AuthAgent | thought | _Verifying identity for customer C003._ |
| 5 | AuthAgent | action | `verify_identity({"customer_id": "C003", "pin": "****"})` |
| 6 | AuthAgent | observation | `verify_identity` → `{"verified": true}` |
| 7 | AuthAgent | action | `issue_session({"customer_id": "C003"})` |
| 8 | AuthAgent | observation | `issue_session` → `{"session_token": "sess_31081e644773", "customer_id": "C003", "expires_in_s": 900}` |
| 9 | AuthAgent | action | `record_audit({"agent": "AuthAgent", "event": "login_success", "details": {"customer_id": "C003"}})` |
| 10 | AuthAgent | observation | `record_audit` → `{"logged": true, "seq": 1}` |
| 11 | AuthAgent | thought | _PIN correct; session issued._ |
| 12 | AuthAgent | message | → **ConciergeAgent** [reply:authenticate] `{"status": "verified", "session_token": "sess_31081e644773", "customer_id": "C003"}` |
| 13 | ConciergeAgent | action | `parse_request({"text": "Send $6,000 to ACC-1001", "mode": "rules"})` |
| 14 | ConciergeAgent | observation | `parse_request` → `{"intent": "transfer", "account_id": null, "account_type": null, "from_account": null, "from_type": null, "to_account": "ACC-1001", "to_type": null, "amount": 6000.0, "skip_review": false}` |
| 15 | ConciergeAgent | message | → **AccountAgent** [list_my_accounts] `{"session_token": "sess_31081e644773"}` |
| 16 | AccountAgent | action | `resolve_session({"session_token": "sess_31081e644773"})` |
| 17 | AccountAgent | observation | `resolve_session` → `{"valid": true, "customer_id": "C003"}` |
| 18 | AccountAgent | action | `list_accounts({"customer_id": "C003"})` |
| 19 | AccountAgent | observation | `list_accounts` → `{"customer_id": "C003", "accounts": [{"account_id": "ACC-3001", "type": "checking"}]}` |
| 20 | AccountAgent | message | → **ConciergeAgent** [reply:list_my_accounts] `{"status": "ok", "customer_id": "C003", "accounts": [{"account_id": "ACC-3001", "type": "checking"}]}` |
| 21 | ConciergeAgent | thought | _Asking RiskAgent to review transfer of $6,000.00 ACC-3001 -> ACC-1001._ |
| 22 | ConciergeAgent | message | → **RiskAgent** [assess_transfer] `{"customer_id": "C003", "from_account": "ACC-3001", "to_account": "ACC-1001", "amount": 6000.0}` |
| 23 | RiskAgent | action | `check_payee({"customer_id": "C003", "to_account": "ACC-1001"})` |
| 24 | RiskAgent | observation | `check_payee` → `{"to_account": "ACC-1001", "known_payee": false, "external": false}` |
| 25 | RiskAgent | action | `daily_transfer_total({"from_account": "ACC-3001"})` |
| 26 | RiskAgent | observation | `daily_transfer_total` → `{"from_account": "ACC-3001", "total_last_24h": 0}` |
| 27 | RiskAgent | thought | _Hard limit hit: amount exceeds single-transfer limit $5,000. Denying._ |
| 28 | RiskAgent | action | `record_audit({"agent": "RiskAgent", "event": "transfer_denied", "details": {"customer_id": "C003", "from": "ACC-3001", "to": "ACC-1001", "amount": 6000.0, "reasons": ["amount exceeds single-transfer limit $5,000"]}})` |
| 29 | RiskAgent | observation | `record_audit` → `{"logged": true, "seq": 2}` |
| 30 | RiskAgent | message | → **ConciergeAgent** [reply:assess_transfer] `{"decision": "deny", "reasons": ["amount exceeds single-transfer limit $5,000"]}` |
| 31 | ConciergeAgent | response | → User: "I can't make this transfer: amount exceeds single-transfer limit $5,000." |

## Audit log at end of run

| seq | agent | event | details |
|---|---|---|---|
| 1 | AuthAgent | login_success | `{"customer_id": "C003"}` |
| 2 | RiskAgent | transfer_denied | `{"customer_id": "C003", "from": "ACC-3001", "to": "ACC-1001", "amount": 6000.0, "reasons": ["amount exceeds single-transfer limit $5,000"]}` |
