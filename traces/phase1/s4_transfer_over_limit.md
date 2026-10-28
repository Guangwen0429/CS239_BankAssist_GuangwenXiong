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
| 4 | AuthAgent | thought | _ConciergeAgent asks me to verify customer C003. I check the PIN with verify_identity; a session is issued only if it is correct (P1)._ |
| 5 | AuthAgent | action | `verify_identity({"customer_id": "C003", "pin": "****"})` |
| 6 | AuthAgent | observation | `verify_identity` → `{"verified": true}` |
| 7 | AuthAgent | action | `issue_session({"customer_id": "C003"})` |
| 8 | AuthAgent | observation | `issue_session` → `{"session_token": "sess_31081e644773", "customer_id": "C003", "expires_in_s": 900}` |
| 9 | AuthAgent | action | `record_audit({"agent": "AuthAgent", "event": "login_success", "details": {"customer_id": "C003"}})` |
| 10 | AuthAgent | observation | `record_audit` → `{"logged": true, "seq": 1}` |
| 11 | AuthAgent | thought | _PIN correct. Session issued (valid 15 minutes); I reply with the status, customer ID and session token, never the PIN (P16)._ |
| 12 | AuthAgent | message | → **ConciergeAgent** [reply:authenticate] `{"status": "verified", "session_token": "sess_31081e644773", "customer_id": "C003"}` |
| 13 | ConciergeAgent | action | `parse_request({"text": "Send $6,000 to ACC-1001", "mode": "rules"})` |
| 14 | ConciergeAgent | observation | `parse_request` → `{"intent": "transfer", "account_id": null, "account_type": null, "from_account": null, "from_type": null, "to_account": "ACC-1001", "to_type": null, "amount": 6000.0, "skip_review": false}` |
| 15 | ConciergeAgent | thought | _The customer wants to send $6,000.00 from their default account to ACC-1001. Plan: resolve the accounts, have RiskAgent review it, and execute only with RiskAgent's approval (P8)._ |
| 16 | ConciergeAgent | message | → **AccountAgent** [list_my_accounts] `{"session_token": "sess_31081e644773"}` |
| 17 | AccountAgent | action | `resolve_session({"session_token": "sess_31081e644773"})` |
| 18 | AccountAgent | observation | `resolve_session` → `{"valid": true, "customer_id": "C003"}` |
| 19 | AccountAgent | thought | _ConciergeAgent sent list_my_accounts; the session belongs to customer C003._ |
| 20 | AccountAgent | action | `list_accounts({"customer_id": "C003"})` |
| 21 | AccountAgent | observation | `list_accounts` → `{"customer_id": "C003", "accounts": [{"account_id": "ACC-3001", "type": "checking"}]}` |
| 22 | AccountAgent | message | → **ConciergeAgent** [reply:list_my_accounts] `{"status": "ok", "customer_id": "C003", "accounts": [{"account_id": "ACC-3001", "type": "checking"}]}` |
| 23 | ConciergeAgent | thought | _Asking RiskAgent to review transfer of $6,000.00 ACC-3001 -> ACC-1001. RiskAgent gets only the customer ID, the two accounts and the amount (P11)._ |
| 24 | ConciergeAgent | message | → **RiskAgent** [assess_transfer] `{"customer_id": "C003", "from_account": "ACC-3001", "to_account": "ACC-1001", "amount": 6000.0}` |
| 25 | RiskAgent | action | `check_payee({"customer_id": "C003", "to_account": "ACC-1001"})` |
| 26 | RiskAgent | observation | `check_payee` → `{"to_account": "ACC-1001", "known_payee": false, "external": false}` |
| 27 | RiskAgent | action | `daily_transfer_total({"from_account": "ACC-3001"})` |
| 28 | RiskAgent | observation | `daily_transfer_total` → `{"from_account": "ACC-3001", "total_last_24h": 0}` |
| 29 | RiskAgent | thought | _Reviewing $6,000.00 ACC-3001 -> ACC-1001 for C003. Single-transfer limit: FAILS ($6,000.00 vs $5,000). 24h total: ok ($0.00 already sent). Size: large, needs confirmation. Payee: new._ |
| 30 | RiskAgent | thought | _Hard limit hit: amount exceeds single-transfer limit $5,000. Denying; no approval (P10)._ |
| 31 | RiskAgent | action | `record_audit({"agent": "RiskAgent", "event": "transfer_denied", "details": {"customer_id": "C003", "from": "ACC-3001", "to": "ACC-1001", "amount": 6000.0, "reasons": ["amount exceeds single-transfer limit $5,000"]}})` |
| 32 | RiskAgent | observation | `record_audit` → `{"logged": true, "seq": 2}` |
| 33 | RiskAgent | message | → **ConciergeAgent** [reply:assess_transfer] `{"decision": "deny", "reasons": ["amount exceeds single-transfer limit $5,000"]}` |
| 34 | ConciergeAgent | response | → User: "I can't make this transfer: amount exceeds single-transfer limit $5,000. No money was moved." |

## Offline policy audit

No policy violations found (checked by `python3 -m bankassist.policy_audit`).

## Audit log at end of run

| seq | agent | event | details |
|---|---|---|---|
| 1 | AuthAgent | login_success | `{"customer_id": "C003"}` |
| 2 | RiskAgent | transfer_denied | `{"customer_id": "C003", "from": "ACC-3001", "to": "ACC-1001", "amount": 6000.0, "reasons": ["amount exceeds single-transfer limit $5,000"]}` |
