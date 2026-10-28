# BankAssist

BankAssist is a multi-agent assistant for a retail bank. A customer logs in with a customer ID and PIN and then chats in plain English to check balances, look at recent transactions and send money. Behind the chat, four agents with separate roles and separate tools work together by exchanging messages:

| Agent | Kind | Role |
|---|---|---|
| **ConciergeAgent** | LLM-based (optional) with rule-based fallback | Customer-facing entry point. Understands each message, asks the other agents for what it needs and writes the reply. Has no access to banking data. |
| **AuthAgent** | Rule-based | Verifies customer ID + PIN, locks a profile after 3 failed attempts, issues session tokens. |
| **AccountAgent** | Rule-based | The only agent that reads balances and transaction history and the only one that can move money. |
| **RiskAgent** | Rule-based | Reviews every transfer against limits, saved payees and external destinations; asks for customer confirmation on risky transfers and issues single-use approvals. |

Coordination is centralized: the ConciergeAgent is the single entry point and routes structured requests over a message bus. Interactions are dynamic; which agents are contacted, and in what order, depends on the request and on earlier replies (for example, a large transfer adds a confirmation round-trip with the RiskAgent).

## Supported tasks

1. **Log in.** Customer ID + PIN, verified by the AuthAgent. Three wrong PINs lock the profile.
2. **Check a balance.** For example "What's my checking balance?" or "balance of my savings".
3. **View recent transactions.** For example "Show my recent transactions".
4. **Transfer money.** For example "Send $200 to ACC-2001" or "Transfer $1,500 from savings to ACC-2001". Small transfers to saved payees are approved automatically. Transfers over $1,000, to new payees or to external accounts need the customer to reply YES. Transfers over $5,000 (or over $10,000 per day) are denied.
5. **Confirm or cancel** a pending transfer by replying YES or NO.

## Data

All banking data is mock data kept in memory (`src/bankassist/bank.py`) and reset on every run: three customers (Alice `C001`, Bob `C002`, Carol `C003`), five accounts and a short transaction history. Nothing connects to a real bank.

## Phase 1 status

This is the Phase 1 prototype, built **without** a safety-enforcing framework. It works for normal requests, but some policies in `policy.md` are not enforced yet. In particular, P5/P6 (a customer can read, or even debit, another customer's account by naming its ID) and P8/P9 (an "express" shortcut skips risk review when the customer asks). Episodes 5, 6 and 7 demonstrate these gaps; Phase 2 will enforce them.
