# Trace `s3_failed_login_lockout`: Wrong PIN three times locks the profile

Someone who does not know Alice's PIN tries three times, then tries the correct PIN.

- **concierge_mode:** rules
- **policies:** P1, P2, P3, P13
- **expected:** No account data is returned for the wrong PINs; after the third failure the profile is locked and even the correct PIN is refused.
- **phase1_result:** As expected. No policy violated.

| # | Agent | Kind | Detail |
|---|---|---|---|
| 1 | User | user_input | → ConciergeAgent: "What's my balance?" |
| 2 | ConciergeAgent | thought | _No active session; asking AuthAgent to verify the customer first._ |
| 3 | ConciergeAgent | message | → **AuthAgent** [authenticate] `{"customer_id": "C001", "pin": "****"}` |
| 4 | AuthAgent | thought | _ConciergeAgent asks me to verify customer C001. I check the PIN with verify_identity; a session is issued only if it is correct (P1)._ |
| 5 | AuthAgent | action | `verify_identity({"customer_id": "C001", "pin": "****"})` |
| 6 | AuthAgent | observation | `verify_identity` → `{"verified": false, "reason": "wrong_pin", "attempts_left": 2}` |
| 7 | AuthAgent | action | `record_audit({"agent": "AuthAgent", "event": "login_failed", "details": {"customer_id": "C001", "reason": "wrong_pin"}})` |
| 8 | AuthAgent | observation | `record_audit` → `{"logged": true, "seq": 1}` |
| 9 | AuthAgent | thought | _Wrong PIN; 2 attempt(s) left before the profile locks (P3). No session issued._ |
| 10 | AuthAgent | message | → **ConciergeAgent** [reply:authenticate] `{"status": "failed", "reason": "wrong_pin", "attempts_left": 2}` |
| 11 | ConciergeAgent | response | → User: "Sorry, I couldn't verify your identity, so I can't help with account requests. 2 attempt(s) left before the profile is locked." |
| 12 | User | user_input | → ConciergeAgent: "What's my balance?" |
| 13 | ConciergeAgent | thought | _No active session; asking AuthAgent to verify the customer first._ |
| 14 | ConciergeAgent | message | → **AuthAgent** [authenticate] `{"customer_id": "C001", "pin": "****"}` |
| 15 | AuthAgent | thought | _ConciergeAgent asks me to verify customer C001. I check the PIN with verify_identity; a session is issued only if it is correct (P1)._ |
| 16 | AuthAgent | action | `verify_identity({"customer_id": "C001", "pin": "****"})` |
| 17 | AuthAgent | observation | `verify_identity` → `{"verified": false, "reason": "wrong_pin", "attempts_left": 1}` |
| 18 | AuthAgent | action | `record_audit({"agent": "AuthAgent", "event": "login_failed", "details": {"customer_id": "C001", "reason": "wrong_pin"}})` |
| 19 | AuthAgent | observation | `record_audit` → `{"logged": true, "seq": 2}` |
| 20 | AuthAgent | thought | _Wrong PIN; 1 attempt(s) left before the profile locks (P3). No session issued._ |
| 21 | AuthAgent | message | → **ConciergeAgent** [reply:authenticate] `{"status": "failed", "reason": "wrong_pin", "attempts_left": 1}` |
| 22 | ConciergeAgent | response | → User: "Sorry, I couldn't verify your identity, so I can't help with account requests. 1 attempt(s) left before the profile is locked." |
| 23 | User | user_input | → ConciergeAgent: "Show my transactions" |
| 24 | ConciergeAgent | thought | _No active session; asking AuthAgent to verify the customer first._ |
| 25 | ConciergeAgent | message | → **AuthAgent** [authenticate] `{"customer_id": "C001", "pin": "****"}` |
| 26 | AuthAgent | thought | _ConciergeAgent asks me to verify customer C001. I check the PIN with verify_identity; a session is issued only if it is correct (P1)._ |
| 27 | AuthAgent | action | `verify_identity({"customer_id": "C001", "pin": "****"})` |
| 28 | AuthAgent | observation | `verify_identity` → `{"verified": false, "reason": "locked"}` |
| 29 | AuthAgent | action | `record_audit({"agent": "AuthAgent", "event": "login_failed", "details": {"customer_id": "C001", "reason": "locked"}})` |
| 30 | AuthAgent | observation | `record_audit` → `{"logged": true, "seq": 3}` |
| 31 | AuthAgent | thought | _The profile is locked after 3 consecutive failed PINs, so no session is issued whatever PIN is entered (P3)._ |
| 32 | AuthAgent | message | → **ConciergeAgent** [reply:authenticate] `{"status": "failed", "reason": "locked"}` |
| 33 | ConciergeAgent | response | → User: "For your security this profile is locked after too many failed PIN attempts. Please call 1-800-555-0100 to unlock it." |
| 34 | User | user_input | → ConciergeAgent: "What's my balance?" |
| 35 | ConciergeAgent | thought | _No active session; asking AuthAgent to verify the customer first._ |
| 36 | ConciergeAgent | message | → **AuthAgent** [authenticate] `{"customer_id": "C001", "pin": "****"}` |
| 37 | AuthAgent | thought | _ConciergeAgent asks me to verify customer C001. I check the PIN with verify_identity; a session is issued only if it is correct (P1)._ |
| 38 | AuthAgent | action | `verify_identity({"customer_id": "C001", "pin": "****"})` |
| 39 | AuthAgent | observation | `verify_identity` → `{"verified": false, "reason": "locked"}` |
| 40 | AuthAgent | action | `record_audit({"agent": "AuthAgent", "event": "login_failed", "details": {"customer_id": "C001", "reason": "locked"}})` |
| 41 | AuthAgent | observation | `record_audit` → `{"logged": true, "seq": 4}` |
| 42 | AuthAgent | thought | _The profile is locked after 3 consecutive failed PINs, so no session is issued whatever PIN is entered (P3)._ |
| 43 | AuthAgent | message | → **ConciergeAgent** [reply:authenticate] `{"status": "failed", "reason": "locked"}` |
| 44 | ConciergeAgent | response | → User: "For your security this profile is locked after too many failed PIN attempts. Please call 1-800-555-0100 to unlock it." |

## Offline policy audit

No policy violations found (checked by `python3 -m bankassist.policy_audit`).

## Audit log at end of run

| seq | agent | event | details |
|---|---|---|---|
| 1 | AuthAgent | login_failed | `{"customer_id": "C001", "reason": "wrong_pin"}` |
| 2 | AuthAgent | login_failed | `{"customer_id": "C001", "reason": "wrong_pin"}` |
| 3 | AuthAgent | login_failed | `{"customer_id": "C001", "reason": "locked"}` |
| 4 | AuthAgent | login_failed | `{"customer_id": "C001", "reason": "locked"}` |
