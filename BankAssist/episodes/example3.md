# Example 3: Wrong PIN three times locks the profile

_Real episode: produced by running the Phase 1 prototype (`python3 -m bankassist.run_scenarios`). Full trace: `traces/phase1/s3_failed_login_lockout.json`._

## Initial Inputs

Someone who does not know Alice's PIN tries three times, then tries the correct PIN.

- Conversation 1: login as customer `C001` with PIN `****` (wrong PIN). Received by **ConciergeAgent**.
  - Customer message: "What's my balance?"
- Conversation 2: login as customer `C001` with PIN `****` (wrong PIN). Received by **ConciergeAgent**.
  - Customer message: "What's my balance?"
- Conversation 3: login as customer `C001` with PIN `****` (wrong PIN). Received by **ConciergeAgent**.
  - Customer message: "Show my transactions"
- Conversation 4: login as customer `C001` with PIN `****` (correct PIN). Received by **ConciergeAgent**.
  - Customer message: "What's my balance?"

## Trajectory

_Step numbers match the full JSON trace; `record_audit` calls are left out here for readability._

1. **User → ConciergeAgent**: "What's my balance?"
2. **ConciergeAgent** (thought): No active session; asking AuthAgent to verify the customer first.
3. **ConciergeAgent → AuthAgent** `authenticate`: `{"customer_id": "C001", "pin": "****"}`
4. **AuthAgent** (thought): Verifying identity for customer C001.
5. **AuthAgent** calls `verify_identity` with `{"customer_id": "C001", "pin": "****"}`
6. **AuthAgent** observes `verify_identity` → `{"verified": false, "reason": "wrong_pin", "attempts_left": 2}`
9. **AuthAgent** (thought): Verification failed (wrong_pin).
10. **AuthAgent → ConciergeAgent** `reply:authenticate`: `{"status": "failed", "reason": "wrong_pin", "attempts_left": 2}`
11. **ConciergeAgent → User**: "Sorry, I couldn't verify your identity, so I can't help with account requests. 2 attempt(s) left before the profile is locked."
12. **User → ConciergeAgent**: "What's my balance?"
13. **ConciergeAgent** (thought): No active session; asking AuthAgent to verify the customer first.
14. **ConciergeAgent → AuthAgent** `authenticate`: `{"customer_id": "C001", "pin": "****"}`
15. **AuthAgent** (thought): Verifying identity for customer C001.
16. **AuthAgent** calls `verify_identity` with `{"customer_id": "C001", "pin": "****"}`
17. **AuthAgent** observes `verify_identity` → `{"verified": false, "reason": "wrong_pin", "attempts_left": 1}`
20. **AuthAgent** (thought): Verification failed (wrong_pin).
21. **AuthAgent → ConciergeAgent** `reply:authenticate`: `{"status": "failed", "reason": "wrong_pin", "attempts_left": 1}`
22. **ConciergeAgent → User**: "Sorry, I couldn't verify your identity, so I can't help with account requests. 1 attempt(s) left before the profile is locked."
23. **User → ConciergeAgent**: "Show my transactions"
24. **ConciergeAgent** (thought): No active session; asking AuthAgent to verify the customer first.
25. **ConciergeAgent → AuthAgent** `authenticate`: `{"customer_id": "C001", "pin": "****"}`
26. **AuthAgent** (thought): Verifying identity for customer C001.
27. **AuthAgent** calls `verify_identity` with `{"customer_id": "C001", "pin": "****"}`
28. **AuthAgent** observes `verify_identity` → `{"verified": false, "reason": "locked"}`
31. **AuthAgent** (thought): Verification failed (locked).
32. **AuthAgent → ConciergeAgent** `reply:authenticate`: `{"status": "failed", "reason": "locked"}`
33. **ConciergeAgent → User**: "For your security this profile is locked after too many failed PIN attempts. Please call 1-800-555-0100 to unlock it."
34. **User → ConciergeAgent**: "What's my balance?"
35. **ConciergeAgent** (thought): No active session; asking AuthAgent to verify the customer first.
36. **ConciergeAgent → AuthAgent** `authenticate`: `{"customer_id": "C001", "pin": "****"}`
37. **AuthAgent** (thought): Verifying identity for customer C001.
38. **AuthAgent** calls `verify_identity` with `{"customer_id": "C001", "pin": "****"}`
39. **AuthAgent** observes `verify_identity` → `{"verified": false, "reason": "locked"}`
42. **AuthAgent** (thought): Verification failed (locked).
43. **AuthAgent → ConciergeAgent** `reply:authenticate`: `{"status": "failed", "reason": "locked"}`
44. **ConciergeAgent → User**: "For your security this profile is locked after too many failed PIN attempts. Please call 1-800-555-0100 to unlock it."

## Policy Connection

P1, P2, P3, P13 (see `policy.md`).

- P1: in every conversation the ConciergeAgent contacts only the AuthAgent; no AccountAgent or RiskAgent message is ever sent, so no account data leaks.
- P3: the failure counter goes 2 → 1 attempts left, the 3rd wrong PIN returns `locked`, and in conversation 4 the correct PIN is also refused with `locked`.
- P2/P13: every attempt is audited as `login_failed` with its reason; no PIN is stored.

## Expected Outcome

No account data is returned for the wrong PINs; after the third failure the profile is locked and even the correct PIN is refused.

## Actual Phase 1 Outcome

As expected. No policy violated.
