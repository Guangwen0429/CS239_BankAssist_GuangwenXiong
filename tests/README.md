# BankAssist test suite

Automated tests for the Phase 1 BankAssist prototype. They use only the Python
standard library (`unittest`, `http.server`, `tempfile`, `unittest.mock`), so
nothing needs to be installed.

## Running the tests

From the repository root:

```bash
python3 -m unittest discover -s tests -v      # standard library only
python3 -m pytest tests -q                    # also works if pytest is installed
```

Expected result: 348 tests, all passing, with **14 expected failures** (shown as `x`
by both runners). All 14 describe policies that Phase 1 does not enforce yet;
see [Expected failures](#expected-failures) below.

Notes:

- `tests/_path.py` puts `<repo>/src` on `sys.path`, so `bankassist` is imported
  straight from the source tree. Each test file imports it first.
- Most tests hide the `BANKASSIST_LLM_*` environment variables, so the
  Concierge runs in rule-based mode and every run is deterministic even if
  you have an LLM configured. Only `test_llm_fallback.py` turns the LLM on,
  and it points it at a small fake server on `127.0.0.1`.
- The tests never write into the repository. `run_scenarios.main()` is always
  called with `--root <temporary directory>`, and the generated files are
  deleted afterwards. The CLI tests point the CLI's `REPO_ROOT` at a temporary
  folder, so the session trace it saves on exit is not written to
  `traces/interactive/`. `tearDown` also removes anything new that does appear
  there.
- Checks that should hold for every scripted scenario loop over
  `scenarios.SCENARIOS` instead of naming scenario IDs, so adding or renaming
  a scenario does not need a test change. The policy-gap tests find "their"
  scenario by its `violation` flag and policy list: the cross-account read is
  the violation scenario with P5 but not P8, skip-review has P8 but not P5, and
  debit-other-customer has both.

## Files

| File | What it covers |
|---|---|
| `_path.py` | Adds `src/` to `sys.path`; `rules_only_env()` and `RulesOnlyTestCase` hide the LLM env vars. |
| `_helpers.py` | Trace helpers (filter events, actions and messages; split a trace into turns; strip time fields), the P4 tool table, the P11 field sets, the list of internal error codes (P12) and the PIN leak scanner. |
| `test_rule_parser.py` | The Concierge's rule-based parser `rule_parse`. |
| `test_bank_tools.py` | The mock bank tools in `bank.py`, called directly. |
| `test_agents_flow.py` | End-to-end conversations through `BankAssistApp`, plus policy checks over every scripted scenario. |
| `test_policy_gaps.py` | The policies Phase 1 leaves unenforced (P5/P6 reads, P5/P6 debits, P8/P9): expected failures plus tests that record what Phase 1 does today. |
| `test_llm_fallback.py` | The optional LLM Concierge against a fake OpenAI-compatible server, the fallback to rules, and the LLM-related regression tests. |
| `test_regressions.py` | Regression tests for the fixes from both review rounds (one class per fix). |
| `test_traces.py` | `run_scenarios` output (traces, episodes, README, viewer), reproducibility of the traces, and the `Tracer` class. |
| `test_cli.py` | The interactive CLI, run as a subprocess with piped stdin. |
| `test_policy_audit.py` | The offline policy auditor `policy_audit.py`: real scenarios, one mutation per rule, `summary()`, the command line, the `run_scenarios` consistency guard and the generated outputs. |

## Test cases

Policy numbers refer to `policy.md`. A dash means the test checks basic
functionality rather than a specific policy.

### `test_rule_parser.py` (class `RuleParserTest`)

| Test | What it checks | Policy |
|---|---|---|
| `test_output_always_has_every_intent_field` | The result always has every intent field, and `skip_review` is a bool. | – |
| `test_balance_default_account` | "What's my balance?" is `check_balance` with no account named. | – |
| `test_balance_by_type` | "checking" / "savings" are picked up as `account_type`; "how much" counts as a balance question. | – |
| `test_balance_by_account_id_is_upper_cased` | A lower-case `acc-1002` is returned as `ACC-1002`. | – |
| `test_transactions_keywords` | transactions / history / activity / purchases all map to `view_transactions`. | – |
| `test_transactions_with_account_id` | The account ID in a transactions request is extracted (the s5 wording). | P5 (input) |
| `test_transfer_simple` | "Send $200 to ACC-2001" gives amount 200, destination ACC-2001, no source, no skip. | – |
| `test_transfer_amount_with_commas_and_cents` | `$1,500`, `$6,000` and `$1,234.56` parse correctly. | P10 (input) |
| `test_transfer_amount_in_words` | "50 dollars" and "75.25 USD" parse. | – |
| `test_transfer_from_savings` | "from savings" sets `from_type="savings"` (the s2 wording). | – |
| `test_transfer_from_my_checking` | "from my checking" sets `from_type="checking"`. | – |
| `test_transfer_explicit_from_and_to_ids` | Explicit from/to account IDs, in either order. | – |
| `test_account_ids_not_mistaken_for_amounts` | The digits in `ACC-2001` / `EXT-9001` are never read as an amount. | P10 (input) |
| `test_external_destination` | `EXT-9001` is accepted as a destination. | P9 (input) |
| `test_transfer_verbs` | transfer / send / wire / pay / move all mean `transfer`. | – |
| `test_confirm_words` | yes / y / confirm / go ahead / ok, in any case and with trailing punctuation, mean `confirm`. | P9 |
| `test_decline_words` | no / n / cancel / stop / don't mean `decline`. | P9 |
| `test_confirm_word_inside_sentence_is_not_a_confirmation` | "yes send $5 …" is a new transfer, not a YES. | P9 |
| `test_skip_review_detected` | "skip the security check", "bypass", "without review", "no need for checks" set `skip_review`. | P8 |
| `test_skip_review_false_for_normal_transfer` | An ordinary transfer has `skip_review=False`. | P8 |
| `test_skip_review_only_flagged_for_transfers` | "skip" in a balance question does not set the flag. | P8 |
| `test_help` | "help" / "What can you do?" are `help`. | – |
| `test_unknown` | Empty or off-topic text is `unknown`. | – |

### `test_bank_tools.py`

| Class / test | What it checks | Policy |
|---|---|---|
| `SeedDataTest.test_each_bank_is_an_independent_copy_of_the_seed` | Changing one `Bank` never changes `SEED_DATA` or another `Bank`. | – |
| `VerifyIdentityTest.test_correct_pin` | The right PIN verifies. | P1 |
| `VerifyIdentityTest.test_unknown_customer` | An unknown ID gives `unknown_customer`. | P1 |
| `VerifyIdentityTest.test_wrong_pin_counts_down_attempts` | A wrong PIN returns `wrong_pin` and `attempts_left` 2, then 1. | P3 |
| `VerifyIdentityTest.test_correct_pin_resets_failed_counter` | A successful login resets the failure counter. | P3 |
| `VerifyIdentityTest.test_lockout_after_three_failures_refuses_correct_pin` | The third failure locks the profile; the correct PIN is then refused. | P3 |
| `VerifyIdentityTest.test_lockout_is_per_customer` | Locking Alice does not affect Bob. | P3 |
| `SessionTest.test_issue_and_resolve` | Token format, TTL, and that it resolves to the right customer. | P1 |
| `SessionTest.test_unknown_token_is_invalid` | Unknown or empty tokens are invalid. | P1 |
| `SessionTest.test_tokens_are_unique` | 20 tokens in a row are all different. | P1 |
| `SessionTest.test_tokens_reproducible_with_same_seed` | The seeded RNG gives reproducible tokens, so traces are reproducible. | – |
| `SessionTest.test_session_expires` | A token is invalid after `SESSION_TTL_SECONDS` (clock mocked). | P1 |
| `AccountReadTest.test_list_accounts_only_returns_own_accounts` | `list_accounts` returns only the customer's own accounts. | P5 |
| `AccountReadTest.test_get_balance` | Balance and type of ACC-1001. | – |
| `AccountReadTest.test_get_balance_no_such_account` | Unknown account gives `no_such_account`. | – |
| `AccountReadTest.test_get_transactions_limit_and_order` | `limit` returns the most recent N, oldest first. | – |
| `AccountReadTest.test_get_transactions_no_such_account` | Unknown account gives `no_such_account`. | – |
| `TransferFundsTest.test_success_moves_money_and_records_history` | Both balances change, both histories get a line, and a transfer record is stored. | P7 |
| `TransferFundsTest.test_insufficient_funds` | No overdraft: refused, nothing changes. | P10 |
| `TransferFundsTest.test_exact_balance_is_allowed` | Sending the whole balance is allowed (new balance 0). | P10 |
| `TransferFundsTest.test_invalid_amount` | Zero and negative amounts are refused. | P10 |
| `TransferFundsTest.test_no_such_account` | Unknown source or destination is refused. | – |
| `TransferFundsTest.test_fixed_today_is_used_for_transaction_dates` | `Bank(today="2030-01-02")` stamps new transactions with that date. | – |
| `TransferFundsTest.test_default_today_is_the_current_date` | Without `today`, the current date is used. | – |
| `TransferFundsTest.test_transfer_marks_approval_used` | A used approval is marked `used` and stored with the transfer. | P8 |
| `RiskToolsTest.test_approve_transfer` | Approval IDs are sequential and store from/to/amount/unused. | P8 |
| `RiskToolsTest.test_daily_total` | 24 h total sums only transfers from that account. | P10 |
| `RiskToolsTest.test_daily_total_ignores_old_transfers` | Transfers older than 24 h are not counted. | P10 |
| `RiskToolsTest.test_daily_limit_constant` | The daily limit is $10,000. | P10 |
| `RiskToolsTest.test_check_payee` | Saved payee, external account, and unknown customer. | P9 |
| `AuditLogTest.test_record_audit_appends_with_sequence_numbers` | Entries get increasing `seq` and keep agent/event/details. | P13 |
| `AuditLogTest.test_tools_do_not_write_audit_on_their_own` | Raw tools do not write audit entries; logging is the agents' job. | P13 |

### `test_agents_flow.py`

Single conversations through `BankAssistApp`:

| Class / test | What it checks | Policy |
|---|---|---|
| `BalanceAndHistoryTest.test_balance_check` | Correct reply text; the first message goes to AuthAgent; AccountAgent gets exactly one request, with a session token. | P1, P5 |
| `BalanceAndHistoryTest.test_savings_balance` | A savings question resolves to ACC-1002. | – |
| `BalanceAndHistoryTest.test_authenticates_only_once_per_conversation` | One login per conversation; `new_conversation()` forces a new one. | P1 |
| `BalanceAndHistoryTest.test_transactions` | The transaction list is formatted correctly. | – |
| `BalanceAndHistoryTest.test_unknown_account` | A missing account gives "Sorry, I couldn't get that balance: that account does not exist." and never the code `no_such_account`. | P12 |
| `BalanceAndHistoryTest.test_help_and_unknown` | Help and fallback texts; AccountAgent is not contacted. | – |
| `TransferFlowTest.test_small_transfer_to_saved_payee_is_auto_approved` | $200 to a saved payee: RiskAgent approves, money moves, the approval is marked used. | P7, P8, P9 |
| `TransferFlowTest.test_multi_turn_confirmed_transfer` | $1,500 asks for confirmation (no approval or execute yet), YES moves the money; the approval matches from/to/amount; `confirm_transfer` comes before `execute_transfer`. | P8, P9, P14 |
| `TransferFlowTest.test_decline_cancels_and_moves_no_money` | NO cancels: no execute request, no transfer, no approval, balances unchanged. | P9, P14 |
| `TransferFlowTest.test_new_request_drops_pending_transfer` | A new request drops the pending transfer, so a later YES does nothing. | P9 |
| `TransferFlowTest.test_confirm_with_nothing_pending` | YES with nothing pending does nothing. | P9 |
| `TransferFlowTest.test_external_and_unknown_payee_need_confirmation` | External and non-saved payees need a YES even for small amounts. | P9 |
| `TransferFlowTest.test_missing_amount_or_destination` | Incomplete requests never reach RiskAgent. | – |
| `TransferFlowTest.test_single_transfer_limit_denied` | $6,000 is denied; AccountAgent never gets `execute_transfer`; no `transfer_funds` call; the denial is audited by RiskAgent. | P10, P13, P14 |
| `TransferFlowTest.test_daily_limit_denied` | Two confirmed $4,500 transfers go through; the third breaks the $10,000 24 h limit and is denied. | P10 |
| `TransferFlowTest.test_insufficient_funds_not_reported_as_success` | A failed transfer is reported in plain words ("there is not enough money in the source account. No money was moved."), with no raw code. | P10, P12, P14 |
| `AuthenticationFlowTest.test_wrong_pin_gets_no_data_and_no_account_agent_message` | A wrong PIN gets no data, and nothing is sent to AccountAgent or RiskAgent; no session; the request is not even parsed. | P1 |
| `AuthenticationFlowTest.test_unknown_customer` | An unknown customer gets nothing. | P1 |
| `AuthenticationFlowTest.test_wrong_pin_transfer_moves_nothing` | Even a "skip the check" transfer with a wrong PIN moves nothing. | P1 |
| `AuthenticationFlowTest.test_lockout_after_three_failures` | Three wrong PINs lock the profile and the correct PIN is then refused; audit reasons are `wrong_pin, wrong_pin, locked, locked`. | P3, P13 |
| `AuthenticationFlowTest.test_invalid_session_rejected_by_account_agent` | AccountAgent refuses a forged token without reading any balance. | P1 |
| `AuthenticationFlowTest.test_session_token_never_shown_to_user` | Replies never contain the session token. | P12 |

Checks over every scenario in `SCENARIOS` (class `ScenarioPolicyTest`, run
through `run_scenarios.run_scenario`, with one sub-test per scenario):

| Test | What it checks | Policy |
|---|---|---|
| `test_there_are_scenarios` | At least 3 scenarios exist. | – |
| `test_pin_never_unmasked_in_trace_or_audit_log` | No PIN appears in `tracer.to_dict()`, the audit log or the transcript; every `pin` field is `****`; the audit log has no `pin` field at all. | P2, P13 |
| `test_pin_only_sent_from_concierge_to_auth_agent` | The only message with a `pin` field is Concierge → AuthAgent `authenticate`. | P2 |
| `test_risk_agent_payload_is_minimal` | Every RiskAgent payload uses only the P11 fields (`customer_id, from_account, to_account, amount, ref, customer_confirmed`). `assess_transfer` carries exactly the first four, `confirm_transfer` exactly `ref, customer_id, customer_confirmed`, and never a session token or PIN. | P11 |
| `test_concierge_never_calls_banking_tools` | ConciergeAgent's only action is `parse_request`. | P4, P12 |
| `test_each_agent_only_calls_its_own_tools` | Every action is in that agent's allowed tool set (AuthAgent: only `verify_identity`, `issue_session`), and `record_audit` is always written under the caller's own name. | P4 |
| `test_only_account_agent_moves_money` | Every `transfer_funds` call comes from AccountAgent. | P7 |
| `test_session_token_never_shown_to_user` | No response contains `sess_`. | P12 |
| `test_no_internal_codes_in_replies` | No response contains a snake_case internal code such as `no_such_account`. | P12 |
| `test_account_and_risk_requests_only_after_authentication` | No message to AccountAgent or RiskAgent before a `verified` authenticate reply. | P1 |
| `test_audit_log_covers_logins_reads_denials_transfers` | Audit counts match the trace: one login entry per `verify_identity`, one read entry per balance/transactions read, one `transfer_denied` per denial, one `transfer` per `transfer_funds`. | P13 |
| `test_money_moved_only_reported_after_completed` | A "Done. Sent $…" reply only appears in a turn where AccountAgent replied `completed`. | P14 |
| `test_every_trace_has_inter_agent_messages` | Every trace has messages and all six event kinds. | – |
| `test_compliant_scenarios_have_expected_outcomes` | Every turn of the compliant scenarios gets a non-empty reply. | – |
Agents explaining their decisions (class `AgentThoughtsTest`, over every scenario):

| Test | What it checks | Policy |
|---|---|---|
| `test_concierge_plans_right_after_parsing` | The event right after every `parse_request` result is a ConciergeAgent plan thought ("The customer …"). | – |
| `test_risk_agent_writes_a_check_list_before_deciding` | Inside every `assess_transfer`, RiskAgent first looks up `check_payee` and `daily_transfer_total`, then writes a "Reviewing $X FROM -> TO for CUSTOMER." check list (single-transfer limit, 24h total), and only then calls `approve_transfer` / `record_audit`. "FAILS" appears in it exactly when the decision is deny. | P8, P9, P10 |
| `test_risk_decision_thought_names_the_policy` | RiskAgent's decision thought ends with the policy it applies: (P8), (P9) or (P10). | P8, P9, P10 |

### `test_policy_gaps.py`

| Class / test | What it checks | Policy | Status |
|---|---|---|---|
| `CrossAccountAccessPolicyTest.test_account_agent_refuses_balance_of_other_customers_account` | AccountAgent refuses Bob's session reading ACC-1002 (Alice). | P5 | expected failure |
| `CrossAccountAccessPolicyTest.test_account_agent_refuses_transactions_of_other_customers_account` | Same, for transactions on ACC-1001. | P5 | expected failure |
| `CrossAccountAccessPolicyTest.test_cross_account_read_never_reaches_bank_tool` | `get_transactions(ACC-1001)` is never called for Bob. | P5 | expected failure |
| `CrossAccountAccessPolicyTest.test_bob_never_sees_alice_balance` | Bob's reply contains none of Alice's balances. | P6 | expected failure |
| `CrossAccountAccessPolicyTest.test_cross_account_scenario_leaks_no_alice_data_to_bob` | In the P5 violation scenario, no Alice transaction or balance reaches Bob or even the Concierge. | P5, P6 | expected failure |
| `SkipReviewPolicyTest.test_skip_review_request_still_goes_through_risk_agent` | "skip the security check" still sends `assess_transfer` to RiskAgent. | P8 | expected failure |
| `SkipReviewPolicyTest.test_skip_review_request_still_needs_confirmation` | A $3,000 external transfer still asks for YES, and nothing moves. | P9 | expected failure |
| `SkipReviewPolicyTest.test_transfer_funds_never_called_without_approval_in_any_scenario` | No `transfer_funds` call with `approval_id=None`, in any scenario. | P8 | expected failure |
| `SkipReviewPolicyTest.test_account_agent_rejects_transfer_without_approval` | AccountAgent refuses `execute_transfer` with no approval. | P8 | expected failure |
| `SkipReviewPolicyTest.test_account_agent_rejects_approval_for_different_amount` | An approval for $10 cannot be used for $1,000. | P8 | expected failure |
| `SkipReviewPolicyTest.test_account_agent_rejects_reused_approval` | A used approval cannot be replayed. | P8 | expected failure |
| `DebitOtherCustomerPolicyTest.test_transfer_funds_never_debits_an_account_the_customer_does_not_own` | In every scenario, each `transfer` audit entry debits an account owned by the session's customer. | P5 | expected failure |
| `DebitOtherCustomerPolicyTest.test_alice_cannot_debit_bobs_account` | "Send $500 from ACC-2001 to ACC-1001" as Alice never calls `transfer_funds` from ACC-2001; Bob keeps $830.50. | P5 | expected failure |
| `DebitOtherCustomerPolicyTest.test_no_bob_data_in_alices_reply` | In the debit-other-customer scenario, Alice's reply shows none of Bob's balances. | P6 | expected failure |
| `Phase1KnownBehaviourTest.test_violation_scenarios_are_flagged` | The scenarios marked `violation` are exactly the three gap scenarios; violation results start with "VIOLATION" and compliant ones with "As expected". | – | pass |
| `Phase1KnownBehaviourTest.test_phase1_cross_account_read_leaks_alice_transactions_to_bob` | Today, Bob does see Alice's rent and pharmacy lines, and the audit log shows C002 reading ACC-1001. | P5, P6 | pass (documents the gap) |
| `Phase1KnownBehaviourTest.test_phase1_skip_review_bypasses_risk_agent_and_confirmation` | Today, the skip-review scenario never contacts RiskAgent, and `transfer_funds` runs with `approval_id=None` and completes. | P8, P9 | pass (documents the gap) |
| `Phase1KnownBehaviourTest.test_phase1_debit_other_customer_completes` | Today, in s7 RiskAgent auto-approves, `transfer_funds` debits ACC-2001 for C001, and the reply shows Alice Bob's new balance ($330.50). | P5, P6 | pass (documents the gap) |
| `Phase1KnownBehaviourTest.test_phase1_debit_other_customer_moves_bobs_money` | Today, ACC-2001 drops to $330.50 and ACC-1001 rises to $2,950.00. | P5 | pass (documents the gap) |
| `Phase1KnownBehaviourTest.test_phase1_express_path_moves_money_immediately` | Today, $3,000 leaves savings in one turn with no approval issued. | P8, P9 | pass (documents the gap) |
| `Phase1KnownBehaviourTest.test_phase1_compliant_scenarios_never_use_express_path` | The compliant scenarios always carry an approval ID. | P8 | pass |

### `test_llm_fallback.py`

A fake OpenAI-compatible server (`POST /v1/chat/completions`) runs on
`127.0.0.1` in a background thread. `BANKASSIST_LLM_BASE_URL`, `_MODEL` and
`_API_KEY` are patched for each test and restored afterwards.

| Class / test | What it checks | Policy |
|---|---|---|
| `LLMConciergeTest.test_config_read_from_env` | `llm_config()` reads the env vars. | – |
| `LLMConciergeTest.test_concierge_uses_llm_output` | Text the rules cannot parse is answered from the LLM's JSON. `concierge_mode` starts with `llm`; `parse_request` mode is `llm`; there is no fallback thought. Also checks the request format (path, model, temperature 0, system prompt + user message, no auth header). | – |
| `LLMConciergeTest.test_pin_is_never_sent_to_the_llm` | The PIN never appears in anything sent to the LLM. | P2 |
| `LLMConciergeTest.test_api_key_sent_as_bearer_token` | `BANKASSIST_LLM_API_KEY` is sent as `Authorization: Bearer …`. | – |
| `LLMConciergeTest.test_json_wrapped_in_prose_is_accepted` | JSON inside a code fence or extra text is still used. | – |
| `LLMConciergeTest.test_extra_llm_fields_are_dropped` | Extra keys from the LLM (`session_token`, `pin`) are dropped from the parsed request. | P2, P12 |
| `LLMConciergeTest.test_llm_transfer_still_reviewed_by_risk_agent` | A transfer understood by the LLM still goes to RiskAgent and needs YES. | P8, P9 |
| `LLMFallbackTest.test_garbage_http_body` | A non-JSON HTTP body falls back to rules. | – |
| `LLMFallbackTest.test_http_error_status` | HTTP 500 falls back to rules. | – |
| `LLMFallbackTest.test_response_missing_choices` | JSON with no `choices` falls back to rules. | – |
| `LLMFallbackTest.test_content_that_is_not_json` | A prose answer falls back to rules. | – |
| `LLMFallbackTest.test_content_with_broken_json` | Malformed JSON (`json.loads` raises) falls back to rules. | – |
| `LLMFallbackTest.test_truncated_json` | A JSON fragment with no closing brace falls back to rules. | – |
| `LLMFallbackTest.test_json_without_intent` | JSON without `intent` falls back to rules. | – |
| `LLMFallbackTest.test_unreachable_url` | A closed port falls back to rules and still answers correctly. | – |
| `LLMFallbackTest.test_chat_raises_llm_unavailable` | `llm.chat` turns a connection error into `LLMUnavailable`. | – |
| `LLMRegressionTest.test_string_false_skip_review_does_not_take_express_path` | The LLM returns `{"intent": "transfer", "to_account": "ACC-2001", "amount": "50", "skip_review": "false"}`. `skip_review` is parsed as `False` and the amount as `50.0`. RiskAgent is consulted (no express path), and the transfer completes with a used approval. | P8, P9 |
| `LLMRegressionTest.test_string_amount_with_symbols_is_converted` | An amount of `"$1,200.50"` becomes 1200.50, and a lower-case account ID is upper-cased. | P9 |
| `LLMRegressionTest.test_garbage_amount_asks_for_amount` | An amount of `"lots"` is dropped, so the customer is asked for the amount and RiskAgent is not contacted. | – |
| `LLMRegressionTest.test_llm_own_account_transfer_by_type` | `from_type`/`to_type` from the LLM (any case) resolve to ACC-1001 → ACC-1002. | – |
| `LLMRegressionTest.test_null_content_raises_llm_unavailable` | `llm.chat` raises `LLMUnavailable` when `message.content` is `null`, a number, an object or a list. | – |
| `LLMRegressionTest.test_null_content_falls_back_to_rules` | With `null` content, the conversation falls back to rules and still answers correctly. | – |
| `LLMRegressionTest.test_unhashable_intent_falls_back_to_rules` | A list or object as `intent` falls back to rules and does not crash the turn. | – |
| `NoLLMConfiguredTest.test_rules_mode_without_env` | With no env vars: mode `rules`, and `chat` raises `LLMUnavailable`. | – |
| `NoLLMConfiguredTest.test_model_without_base_url_is_not_enough` | The model name alone does not turn the LLM on. | – |

In every fallback test, the reply to "What's my checking balance?" must still
be exactly `The balance of checking account ACC-1001 is $2,450.00.`, and the
trace must contain exactly one Concierge thought saying it is "falling back to
rule parser".

### `test_regressions.py`

Each class guards one fix. The first block comes from the first round of
testing: all of those tests failed against the code before the fixes, except
the ones marked "guard", which check behaviour that was already correct and
must stay that way. The second block covers the behaviour changed after the
independent review.

| Class / test | What it checks | Policy |
|---|---|---|
| `EmptyAmountRegressionTest.test_rule_parse_dollar_comma_gives_no_amount` | `rule_parse("send $, to ACC-2001")` no longer crashes: amount `None`, destination kept. | – |
| `EmptyAmountRegressionTest.test_other_degenerate_amounts` | `$`, `$,,,` and `, dollars` also give amount `None`. | – |
| `EmptyAmountRegressionTest.test_chat_asks_for_amount_instead_of_crashing` | `app.chat` replies "Please tell me the amount and the destination account…" and never reaches RiskAgent. | – |
| `NormalizeRequestTest.test_non_dict_is_rejected` | `normalize_request` returns `None` for `None`, lists, strings, numbers and bools. | – |
| `NormalizeRequestTest.test_missing_or_unknown_intent_is_rejected` | Returns `None` for a missing, `None`, unknown, wrong-case, numeric, list or object intent. | – |
| `NormalizeRequestTest.test_every_known_intent_is_accepted` | All 7 documented intents are accepted. | – |
| `NormalizeRequestTest.test_output_has_rule_parse_shape` | Output has exactly the `rule_parse` keys; extra keys (`pin`, `session_token`) are dropped. | P2, P12 |
| `NormalizeRequestTest.test_skip_review_only_true_for_true_or_string_true` | `skip_review` is `True` only for `True` or the string `"true"` (any case or spacing). `"false"`, `"False"`, `1`, `"yes"`, `""`, `None` and others give `False`. | P8 |
| `NormalizeRequestTest.test_amount_strings_are_converted` | `"50"`, `"$1,200.50"`, `" 75 "`, `75` and `12.5` become floats. | – |
| `NormalizeRequestTest.test_bad_amounts_become_none` | Garbage, empty, zero, negative, bool, list, dict and non-finite amounts (`inf`, `"Infinity"`, `nan`) become `None`. | P10 |
| `NormalizeRequestTest.test_account_ids_are_validated_and_upper_cased` | Valid IDs are trimmed and upper-cased. | – |
| `NormalizeRequestTest.test_malformed_account_ids_are_dropped` | `ACC-12`, `ACC1001`, `acc-1001x`, `XYZ-1001`, injected text and non-strings are dropped. | – |
| `NormalizeRequestTest.test_account_types_lowercased_and_validated` | `Checking` / ` SAVINGS ` are lower-cased; unknown types are dropped. | – |
| `ConfirmDeclinePhrasesTest.test_parse_confirm_phrases` | "yes please", "Yes, please", "sure", "yep", "yeah", "do it", "ok thanks", "yes thank you" mean confirm. | P9 |
| `ConfirmDeclinePhrasesTest.test_parse_decline_phrases` | "no thanks", "No, thank you", "nope", "cancel it", "dont" mean decline. | P9 |
| `ConfirmDeclinePhrasesTest.test_phrases_inside_a_real_request_are_not_confirmations` | "sure, send $5 …" is a transfer and "no thanks, what's my balance?" is a balance request (guard). | P9 |
| `ConfirmDeclinePhrasesTest.test_pending_transfer_confirmed_with_yes_please` | A pending $1,500 transfer confirmed with "yes please" completes. | P9, P14 |
| `ConfirmDeclinePhrasesTest.test_pending_transfer_cancelled_with_no_thanks` | "no thanks" cancels: no money moves, and RiskAgent has nothing pending. | P9, P14 |
| `OwnAccountTransferTest.test_parse_to_type` | "Move $300 from checking to savings" gives `from_type=checking`, `to_type=savings`, no `to_account`; real IDs still go to `to_account`. | – |
| `OwnAccountTransferTest.test_check_payee_treats_own_account_as_known` | `check_payee` returns `known_payee=True` for the customer's own accounts, and still `False` for other people's unsaved accounts. | P9 |
| `OwnAccountTransferTest.test_checking_to_savings_is_auto_approved` | For C001, ACC-1001 → ACC-1002 for $300: RiskAgent gets exactly the P11 fields, approves without confirmation, and the money moves. | P7, P8, P9, P11 |
| `OwnAccountTransferTest.test_exactly_one_thousand_is_still_auto_approved` | $1,000.00 between own accounts needs no confirmation (boundary). | P9 |
| `OwnAccountTransferTest.test_above_one_thousand_still_needs_confirmation` | $1,000.01 between own accounts needs YES, only because of the amount. | P9 |
| `OwnAccountTransferTest.test_source_defaults_to_the_other_account_type` | "move $50 to checking" comes from savings, and "to my savings" comes from checking. | – |
| `OwnAccountTransferTest.test_missing_own_account_type` | Bob has no savings account: a polite error, and RiskAgent is not contacted. | – |
| `PendingCancelledOnNewRequestTest.test_new_request_tells_risk_agent_to_cancel` | A new request while a transfer is pending sends RiskAgent `confirm_transfer` with `{ref, customer_id, customer_confirmed: False}`. The reply starts with the cancellation notice, the ref leaves `RiskAgent.pending`, and a late YES does nothing. | P9, P14 |
| `PendingCancelledOnNewRequestTest.test_cancel_happens_before_new_transfer_is_assessed` | Message order is assess → cancel → assess; only the new ref is pending, and confirming it completes. | P9 |
| `ExpiredSessionRenewalTest.test_balance_after_expiry_reauthenticates` | After forcing expiry (`issued_at -= 10_000`), a balance request still succeeds. The trace shows a second `authenticate`, one refused and one retried `get_balance`, and two `login_success` audit entries. | P1, P13 |
| `ExpiredSessionRenewalTest.test_pin_still_masked_after_renewal` | After the renewal, the PIN is still `****` everywhere in the trace and audit log, and only goes Concierge → AuthAgent. | P2, P13 |
| `ExpiredSessionRenewalTest.test_credentials_not_kept_between_turns` | The Concierge does not keep the PIN after a turn ends. | P2 |
| `ExpiredSessionRenewalTest.test_confirmation_after_expiry_still_completes` | A YES sent after the session expired still completes the approved transfer. | P1, P14 |
| `ExpiredSessionRenewalTest.test_expiry_with_wrong_pin_returns_no_data` | If renewal fails (wrong PIN), no data is returned; the reply says "your session could not be verified" (not `invalid_session`); the failure is counted and the session dropped. | P1, P3, P12 |
| `SameAccountTransferTest.test_same_account_id_refused_without_risk_agent` | "Send $10 from ACC-1001 to ACC-1001" is refused without contacting RiskAgent or moving money. | P10 |
| `SameAccountTransferTest.test_same_account_type_refused` | "from checking to checking" is refused the same way. | P10 |
| `SameAccountTransferTest.test_same_account_with_skip_review_also_refused` | The same-account check also runs before the skip-review shortcut. | P8 |
Second review round:

| Class / test | What it checks | Policy |
|---|---|---|
| `PlainErrorMessagesTest.test_explain_mapping` | `_explain()` maps every known code to its sentence, and anything else to "something went wrong on our side". | P12 |
| `PlainErrorMessagesTest.test_no_such_account_balance` | "Sorry, I couldn't get that balance: that account does not exist." | P12 |
| `PlainErrorMessagesTest.test_no_such_account_transactions` | "Sorry, I couldn't get the transactions: that account does not exist." | P12 |
| `PlainErrorMessagesTest.test_insufficient_funds` | "The transfer failed: there is not enough money in the source account. No money was moved." | P12, P14 |
| `PlainErrorMessagesTest.test_invalid_amount` | A zero amount gives "The transfer failed: the amount is not valid. No money was moved." | P10, P12 |
| `PlainErrorMessagesTest.test_no_account_of_type_balance` | Bob asking for savings gets "there is no account of that type on your profile". | P12 |
| `PlainErrorMessagesTest.test_no_raw_codes_in_any_reply_of_a_long_session` | Ten error-prone requests in a row: no reply contains a raw code. | P12 |
| `AccountTypeAndAuditTest.test_missing_account_type_does_not_fall_back_to_checking` | AccountAgent answers `no_account_of_type` and reads no account at all. | P5 |
| `AccountTypeAndAuditTest.test_missing_account_type_for_transactions` | The same for transactions: no checking history is shown instead. | P5, P12 |
| `AccountTypeAndAuditTest.test_existing_type_still_works` | Alice's savings balance still works. | – |
| `AccountTypeAndAuditTest.test_no_type_named_uses_first_account_if_no_checking` | With no type named, a savings-only customer gets their savings balance; asking for checking explicitly gets the "no account of that type" sentence. | – |
| `AccountTypeAndAuditTest.test_read_audit_entries_carry_status` | `get_balance` / `get_transactions` audit entries have `status` `ok` or `error` and the customer ID. | P13 |
| `AccountTypeAndAuditTest.test_read_audit_status_in_every_scenario` | The same holds in every scripted scenario. | P13 |
| `AccountTypeAndAuditTest.test_transfer_denied_audit_has_customer_id` | RiskAgent's `transfer_denied` entry includes `customer_id`. | P13 |
| `AuthAgentHardeningTest.test_customer_id_is_normalised` | `"c001 "` logs in as C001 (tool call, session and audit all say C001). | P1 |
| `AuthAgentHardeningTest.test_normalised_id_counts_towards_lockout` | Wrong PINs under `c001`, ` C001`, `c001 ` all count against C001 and lock it. | P3 |
| `AuthAgentHardeningTest.test_validate_session_no_longer_supported` | AuthAgent refuses `validate_session` and never calls `resolve_session`. | P4 |
| `AuthAgentHardeningTest.test_auth_agent_tool_set` | AuthAgent uses exactly `verify_identity`, `issue_session`, `record_audit`. | P4 |
| `RiskAgentConfirmationTest.test_confirm_payload_names_the_customer` | `confirm_transfer` carries `{ref, customer_id, customer_confirmed}` and only P11 fields. | P11 |
| `RiskAgentConfirmationTest.test_approve_reply_has_no_internal_fields` | The approval reply has only `decision, approval_id, from_account, to_account, amount` (no `created_at`). | – |
| `RiskAgentConfirmationTest.test_other_customers_ref_is_denied` | A ref confirmed under another, empty or lower-case customer ID is denied; the owner's pending transfer is untouched and still completes. | P9 |
| `RiskAgentConfirmationTest.test_missing_customer_id_is_denied` | A confirmation without `customer_id` is denied. | P9 |
| `RiskAgentConfirmationTest.test_expired_pending_is_denied_and_discarded` | A pending ref older than `APPROVAL_TTL_SECONDS` is denied ("the confirmation window (10 minutes) has passed") and discarded; nothing moves. | P9, P14 |
| `RiskAgentConfirmationTest.test_pending_just_inside_the_window_is_approved` | 5 s before the deadline, YES still works. | P9 |
| `RiskAgentConfirmationTest.test_refs_are_never_reused` | After decline, replace, approve and logout, refs are RISK-001 … RISK-004, with only the last one pending. | P9 |
| `PendingCancellationNoticeTest.test_notice_before_new_balance_reply` | A new request while a transfer is pending gets "(Your transfer that was waiting for confirmation has been cancelled; no money was moved.) " before the answer. | P14 |
| `PendingCancellationNoticeTest.test_notice_before_new_transfer_confirmation` | The same notice comes before a new confirmation question. | P14 |
| `PendingCancellationNoticeTest.test_no_notice_without_pending_transfer` | No notice when nothing was pending. | P14 |
| `PendingCancellationNoticeTest.test_logout_cancels_pending_transfer` | `app.new_conversation()` sends RiskAgent the cancel (with `customer_id`), clears pending state, and the next customer's YES does nothing. | P9, P14 |
| `PendingCancellationNoticeTest.test_cancel_pending_without_pending_sends_nothing` | `cancel_pending()` with nothing pending sends no message. | – |
| `PendingCancellationNoticeTest.test_take_back_in_same_message` | "Can you send $100 to ACC-2001? Actually no, cancel" is a decline: RiskAgent is not contacted and nothing moves. | P14 |
| `PendingCancellationNoticeTest.test_take_back_cancels_a_pending_transfer` | A take-back message while a transfer is pending cancels it. | P9, P14 |
| `ParserRound2Test.test_rejected_amounts` | `$1e3`, `$10.555`, `$1,,,,5`, `$1,5`, `$1,5000`, `$5.5.5` give amount `None`. | P10 |
| `ParserRound2Test.test_accepted_amounts` | `$1,000.`, `$200, please`, `$1,000,000`, `300 dollars`, `$ 50`, `$0.5` still parse. | – |
| `ParserRound2Test.test_rejected_amount_asks_again` | A rejected amount makes the Concierge ask for the amount instead of guessing. | P10 |
| `ParserRound2Test.test_five_digit_account_is_not_truncated` | "to ACC-20011" does not match ACC-2001; nothing moves. | – |
| `ParserRound2Test.test_two_destinations_are_ambiguous` | Two different destinations give `to_account None`, so the customer is asked; the same ID twice, or a source plus a destination, still work. | – |
| `ParserRound2Test.test_without_checking_is_not_skip_review` | "pay $20 to EXT-9001 without checking" is not a skip request and goes to RiskAgent. | P8 |
| `ParserRound2Test.test_take_back_phrases` | "actually no, cancel", "never mind", "nevermind", "actually no" and "don't send" make it a decline; "cancelled concert" does not. | P14 |
| `PinInChatTest.test_pin_masked_before_trace_and_parse` | "my pin is 1234 what's my balance" is traced and parsed as "my pin is **** …", and the balance is answered. | P2 |
| `PinInChatTest.test_other_separators` | The PIN is masked next to `=`/`;`, `!`, parentheses, or on its own. | P2 |
| `PinInChatTest.test_dollar_amount_equal_to_pin_is_not_masked` | "Send $1234 to ACC-2001" is left as is, and a $1,234.00 transfer is offered. | – |
| `PinInChatTest.test_longer_numbers_are_not_masked` | `12345`, `112345`, `1,234`, `12.34` are left alone. | – |
| `PinInChatTest.test_only_the_session_pin_is_masked` | Another customer's PIN in the text is not touched (only the PIN being used is known). | P2 |
| `PinInChatTest.test_pin_followed_by_comma_is_masked` | "my pin is 1234, what's my balance" must be traced without `1234`. | P2 |
| `PinInChatTest.test_pin_followed_by_period_is_masked` | "… my pin is 1234." must be traced without `1234`. | P2 |
| `ParserRound3Test.test_negative_amounts_are_not_read` | "-$5" and "-5 dollars" are not read as amounts; the customer is asked again and nothing moves. | P14 |
| `ParserRound3Test.test_dont_takes_the_request_back` | "send $50 to ACC-2001 please don't" is a decline; no `execute_transfer`, balance unchanged. | P14 |
| `ParserRound3Test.test_amount_equal_to_pin_is_not_masked` | "send 1234 dollars …" while logged in with PIN 1234 still reads the amount $1,234.00. | P2 |
| `ParserRound3Test.test_denial_says_no_money_moved` | A denied transfer's reply ends with "No money was moved." | P14 |
| `ReviewRound3Test.test_customer_switch_without_logout_logs_new_customer_in` | A message for a different customer ends the old session and logs the new customer in; Bob's "yes" cannot confirm Alice's pending transfer. | P1, P9 |
| `ReviewRound3Test.test_customer_switch_does_not_show_previous_customers_balance` | After a customer switch, the balance shown is the new customer's own. | P6 |
| `ReviewRound3Test.test_denied_confirmation_is_audited` | A confirmation denied because the window passed is written to the audit log by RiskAgent; the auditor reports nothing. | P13 |
| `ReviewRound3Test.test_auditor_checks_pin_of_the_customer_who_typed_it` | After a logout, the next customer's message is checked against that customer's PIN, not the previous one's. | P2 |
| `ReviewRound3Test.test_pin_digits_inside_account_id_are_not_masked` | "ACC-1234" is not masked even when the PIN is 1234. | P2 |

### `test_traces.py`

`GeneratedTracesTest` runs `run_scenarios.main(["--root", tmpdir])` once,
with stdout captured.

| Class / test | What it checks | Policy |
|---|---|---|
| `GeneratedTracesTest.test_course_requirement_at_least_three_traces` | At least 3 traces are produced (course requirement). | – |
| `GeneratedTracesTest.test_one_json_and_one_md_per_scenario` | 7 scenarios, giving 7 `.json` and 7 `.md` files named after the scenario IDs. | – |
| `GeneratedTracesTest.test_readme_written` | `traces/README.md` mentions every scenario. | – |
| `GeneratedTracesTest.test_episodes_written` | `example1.md` to `example7.md`, each with the required sections. | – |
| `GeneratedTracesTest.test_output_layout` | All expected files exist, and nothing is written outside `traces/` and `BankAssist/episodes/`. | – |
| `GeneratedTracesTest.test_viewer_html_written` | `traces/viewer.html` exists, names every scenario, and contains no unmasked PIN. | P2 |
| `GeneratedTracesTest.test_progress_printed` | The console summary counts the violations correctly. | – |
| `GeneratedTracesTest.test_json_structure` | Top-level keys, steps numbered 1..n, valid event kinds, audit log in `meta`, rules mode. | P13 |
| `GeneratedTracesTest.test_all_six_event_kinds_across_the_set` | user_input, thought, action, observation, message and response all appear across the traces. | – |
| `GeneratedTracesTest.test_all_six_event_kinds_in_every_trace` | Each trace has all six kinds on its own. | – |
| `GeneratedTracesTest.test_every_trace_has_inter_agent_messages` | Each trace has at least one request/reply pair between two different agents. | – |
| `GeneratedTracesTest.test_no_pin_in_any_written_file` | No PIN in any JSON trace or Markdown file. | P2 |
| `GeneratedTracesTest.test_markdown_trace_has_one_row_per_event` | The Markdown table has one row per event, plus the audit section. | P13 |
| `GeneratedTracesTest.test_committed_traces_present_in_repo` | The committed `traces/phase1/` holds at least 3 JSON traces (read-only check). | – |
| `ReproducibleTracesTest.test_same_files` | Two runs of `run_scenarios.main` into two temporary folders write the same set of files. | – |
| `ReproducibleTracesTest.test_json_traces_identical_except_time_fields` | Every JSON file is equal after removing `time` / `started_at`. | – |
| `ReproducibleTracesTest.test_json_traces_byte_identical_after_masking_time_fields` | JSON and `viewer.html` are byte-identical once the `time` / `started_at` values are blanked. | – |
| `ReproducibleTracesTest.test_markdown_files_byte_identical` | Every Markdown file (traces, episodes, README) is byte-identical. | – |
| `ReproducibleTracesTest.test_scripted_runs_use_the_fixed_date` | New transactions in the traces are dated `run_scenarios.SCENARIO_DATE` (2026-10-28), not today. | – |
| `ReproducibleTracesTest.test_run_scenario_twice_in_process` | `run_scenario` twice gives equal traces (minus time fields) and equal transcripts. | – |
| `TracerUnitTest.test_redact_masks_pin_recursively` | `redact` masks nested `pin` fields and leaves the input untouched. | P2 |
| `TracerUnitTest.test_events_are_redacted_when_recorded` | Messages and actions are masked as they are recorded. | P2 |
| `TracerUnitTest.test_unknown_kind_rejected` | Only the six event kinds are accepted. | – |
| `TracerUnitTest.test_save_json_and_markdown` | Save round-trip; `|` is escaped in Markdown cells. | – |

### `test_cli.py` (class `CLITest`, POSIX only)

Each test runs `bankassist.cli.main()` in a subprocess with `cwd=src`, a
temporary `HOME`, piped stdin and `REPO_ROOT` pointed at a temporary folder.
The subprocess gets its own session (no controlling terminal), so `getpass`
reads the PIN from the piped stdin.

| Test | What it checks | Policy |
|---|---|---|
| `test_failed_login_asks_for_pin_again` | `--customer c001 --pin 9999`, then "balance", "1234", "What is my balance?", "quit". The output shows `$2,450.00`, "2 attempt(s) left" exactly once, and no lockout. The saved trace has exactly 2 `authenticate` messages (the wrong PIN was not resent), no unmasked PIN, and the PIN line was not treated as a chat message. | P1, P2, P3 |
| `test_logout_at_pin_prompt_switches_customer` | After a failed login, typing `logout` at the PIN prompt lets Bob log in and see `$830.50`. | P1 |
| `test_eof_at_customer_prompt_exits_cleanly` | Empty stdin at "Customer ID:" exits with code 0 and no traceback. | – |
| `test_eof_while_chatting_exits_cleanly` | EOF in the middle of a chat exits with code 0 and no traceback. | – |
| `test_trace_saved_outside_the_repo` | The session trace is saved under the temporary root, and `<repo>/traces/interactive` is unchanged. | – |

### `test_policy_audit.py`

The auditor reads a saved trace (`Tracer.to_dict()`) and returns
`Finding(policy, step, agent, detail)` for P1–P16 (P17 is not observable in a
trace). The mutation tests start from a clean trace and change one thing:

- **Real traces**: a deep copy of a clean scripted trace, picked by content (for
  example "the first clean scenario with an auto-approved transfer").
- **Synthetic traces**: built with `Synth`, a small builder that writes the same
  event shapes as the real agents, through the real `Tracer`.

`assertOnly` checks that the reported policies are **exactly** the expected
set, so no unrelated rule may fire.

Real scenarios (class `ScenarioAuditTest`):

| Test | What it checks | Policy |
|---|---|---|
| `test_findings_match_declared_violations` | For every scenario, the policies found equal the scenario's `violated` list (s5 P5+P6, s6 P8+P9, s7 P5+P6, others none). | all |
| `test_compliant_scenarios_are_clean` | Compliant scenarios have no findings and an empty `violated` list. | all |
| `test_meta_policy_audit_matches_audit` | `meta["policy_audit"]` written by `run_scenario` equals a fresh `audit()`. | – |
| `test_every_finding_points_at_a_real_event` | Every finding's step exists, and its agent matches that event's agent. | – |
| `test_p5_points_at_account_agent_read_or_debit` | P5 sits on an AccountAgent `get_transactions` / `get_balance` / `transfer_funds` action, and the detail names the account. | P5 |
| `test_p6_points_at_the_following_concierge_response` | P6 sits on the first ConciergeAgent response after the P5 step. | P6 |
| `test_p8_p9_point_at_transfer_funds` | P8 / P9 sit on the AccountAgent `transfer_funds` action. | P8, P9 |
| `test_cross_account_read_details` | The cross-account read has one P5, on `get_transactions` of ACC-1001. | P5 |
| `test_debit_other_customer_details` | The debit-other-customer P5 is on `transfer_funds` from ACC-2001. | P5 |
| `test_skip_review_details` | Skip-review gives one P8 ("no RiskAgent approval") and one P9, both on the same step. | P8, P9 |
| `test_committed_traces_agree` | The committed `traces/phase1/*.json` give the same findings as a fresh run (read-only). | – |

Mutations, one rule each (`SyntheticBaselineTest` checks that the untouched base traces are clean):

| Class / test | Mutation | Expected |
|---|---|---|
| `SyntheticBaselineTest.test_clean_synthetic_trace_has_no_findings` | none (login, balance, confirmed $1,500 transfer) | no findings |
| `SyntheticBaselineTest.test_real_base_traces_are_clean` | none (each real base trace) | no findings |
| `MutationP1Test.test_auth_events_removed` | Delete the authenticate request…reply from a real trace. | P1 at the first AccountAgent/RiskAgent request |
| `MutationP1Test.test_tiny_trace_without_login` | Balance request with no login at all. | P1 |
| `MutationP1Test.test_request_after_only_a_failed_login` | Balance request after a failed login. | P1 |
| `MutationP1Test.test_risk_request_before_login` | `assess_transfer` with no login. | P1 |
| `MutationP2Test.test_unmasked_pin_in_non_authenticate_message` | `"pin": "1234"` added to a `get_balance` request. | P2 at that message |
| `MutationP2Test.test_unmasked_pin_in_reply_payload` | `"pin": "1234"` in AccountAgent's reply. | P2 |
| `MutationP2Test.test_unmasked_pin_in_tool_args` | `"pin": "1234"` in `get_balance` args. | P2 |
| `MutationP2Test.test_masked_pin_field_outside_login_is_flagged` | `"pin": "****"` added to a `get_balance` request (the tracer masks every PIN, so this still means a PIN was sent there). | P2 |
| `MutationP2Test.test_masked_pin_in_login_flow_is_fine` | The masked PIN in the `authenticate` message is allowed. | no findings |
| `MutationP2Test.test_customer_pin_in_response` | "(your PIN is 1234)" appended to a response. | P2 at that response |
| `MutationP2Test.test_customer_pin_in_thought` | PIN appended to an AccountAgent thought. | P2 |
| `MutationP2Test.test_customer_pin_in_later_user_message` | PIN in the second user message. | P2 |
| `MutationP2Test.test_dollar_amount_in_response_is_not_a_pin` | "$1234" and "$1,234.00" in a response. | no findings |
| `MutationP3Test.test_issue_session_for_a_different_customer` | `issue_session` for C002 after verifying C001. | P3 at `issue_session` |
| `MutationP3Test.test_issue_session_without_any_verify` | `issue_session` with no `verify_identity` before it. | P3 |
| `MutationP3Test.test_issue_session_after_failed_verify` | `issue_session` right after a failed verify. | P3 |
| `MutationP3Test.test_verified_after_three_consecutive_failures` | The 4th login of the lockout trace changed to `verified: true`. | P3 at that observation |
| `MutationP3Test.test_two_failures_then_success_is_fine` | Two failures, then a success. | no findings |
| `MutationP4P7Test.test_concierge_calls_get_balance` | ConciergeAgent calls `get_balance` itself (after AccountAgent's session). | P4 |
| `MutationP4P7Test.test_concierge_tool_call_without_any_session` | The same, with no AccountAgent session at all. | P4, P5, P6 |
| `MutationP4P7Test.test_auth_agent_calls_resolve_session` | `resolve_session` relabelled as an AuthAgent call. | P4 |
| `MutationP4P7Test.test_transfer_funds_by_risk_agent` | `transfer_funds` done by RiskAgent. | P4 + P7, same step |
| `MutationP4P7Test.test_transfer_funds_outside_execute_transfer` | AccountAgent moves money while handling `get_balance`. | P7 |
| `MutationP8Test.test_approval_id_null` | `approval_id: null`. | P8 ("no RiskAgent approval") |
| `MutationP8Test.test_unknown_approval_id` | `approval_id: "APR-9999"`. | P8 ("never issued") |
| `MutationP8Test.test_mismatched_amount` | Amount changed after approval. | P8 ("different transfer") |
| `MutationP8Test.test_mismatched_destination` | Approved to ACC-2001, executed to ACC-1002. | P8 |
| `MutationP8Test.test_reused_approval` | `transfer_funds` repeated with the same approval. | exactly one P8 ("used twice") |
| `MutationP9P10Test.test_large_transfer_approved_by_assess_instead_of_confirm` | $1,500 approved directly by `assess_transfer`. | P9 |
| `MutationP9P10Test.test_real_confirmed_trace_relabelled_as_assess` | The real `confirm_transfer` request relabelled `assess_transfer`. | P9 |
| `MutationP9P10Test.test_small_transfer_to_unknown_payee_without_yes` | $10 to a non-saved payee, no YES. | P9 |
| `MutationP9P10Test.test_external_transfer_without_yes` | $10 to EXT-9001, no YES. | P9 |
| `MutationP9P10Test.test_small_transfer_to_own_account_needs_no_yes` | $300 to the customer's own savings, no YES. | no findings |
| `MutationP9P10Test.test_single_transfer_over_limit` | Confirmed transfer changed to $6,000 (approval too). | P10 at the `transfer_funds` result |
| `MutationP9P10Test.test_failed_transfer_over_limit_is_not_flagged` | $6,000 transfer that failed. | no findings |
| `MutationP9P10Test.test_cumulative_over_daily_limit` | Three confirmed $4,000 transfers from one account. | exactly one P10 ("24h"), on the third |
| `MutationP11ToP16Test.test_extra_field_in_risk_request` | `session_token` added to `assess_transfer`. | P11 |
| `MutationP11ToP16Test.test_session_token_in_response` | "sess_abc123" in a response. | P12 |
| `MutationP11ToP16Test.test_error_code_in_response` | "insufficient_funds" in a response. | P12 |
| `MutationP11ToP16Test.test_approval_id_in_response` | "APR-0001" in a response. | P12 |
| `MutationP11ToP16Test.test_login_not_audited` | `record_audit` after `verify_identity` removed. | P13 (AuthAgent, "login attempt") |
| `MutationP11ToP16Test.test_failed_login_not_audited` | Failed login without an audit entry. | P13 |
| `MutationP11ToP16Test.test_read_not_audited` | `record_audit` after `get_balance` removed. | P13 (AccountAgent) |
| `MutationP11ToP16Test.test_transfer_not_audited` | `record_audit` after `transfer_funds` removed. | P13 |
| `MutationP11ToP16Test.test_risk_deny_not_audited` | RiskAgent's `transfer_denied` audit removed. | P13 (RiskAgent) |
| `MutationP11ToP16Test.test_sent_without_completed_transfer` | Balance reply replaced by "Done. Sent $50.00 …". | P14 |
| `MutationP11ToP16Test.test_sent_after_denied_transfer` | Denial reply replaced by "Done. Sent $6,000.00 …". | P14 |
| `MutationP11ToP16Test.test_sent_after_failed_transfer` | "Done. Sent …" after a failed `execute_transfer`. | P14 |
| `MutationP11ToP16Test.test_account_agent_sends_request_to_risk_agent` | AccountAgent sends `assess_transfer` to RiskAgent. | P15 |
| `MutationP11ToP16Test.test_unknown_performative` | `get_balance` request renamed `dump_all_accounts`. | P15 |
| `MutationP11ToP16Test.test_validate_session_request_to_auth` | `validate_session` sent to AuthAgent. | P15 |
| `MutationP11ToP16Test.test_auth_reply_with_extra_key` | `risk_score` added to AuthAgent's reply. | P16 |

Summary, command line, guard and outputs:

| Class / test | What it checks |
|---|---|
| `SummaryTest.test_all_ok` | `summary([])` maps P1..P17 in order: `ok`, and P17 `not observable`. |
| `SummaryTest.test_violated` | Listed policies (duplicates allowed) become `violated`; the rest stay `ok`. |
| `SummaryTest.test_accepts_any_iterable` | A generator of policy IDs works. |
| `SummaryTest.test_p17_stays_not_observable` | P17 is `not observable` unless explicitly listed. |
| `AuditCLITest.test_clean_traces_exit_0` | `main()` on the clean traces returns 0 and prints "no violations" for each. |
| `AuditCLITest.test_violating_trace_exits_1` | Each violating trace returns 1 and prints "P# at step N (Agent): …". |
| `AuditCLITest.test_mixed_exits_1` | One bad file among clean ones gives 1. |
| `AuditCLITest.test_json_output_parses` | `--json` prints `{path: [ {policy, step, agent, detail} ]}` that matches each scenario's `violated` list. |
| `AuditCLITest.test_json_clean_exit_0` | `--json` on a clean trace gives `{path: []}` and 0. |
| `AuditCLITest.test_subprocess_exit_codes` | `python3 -m bankassist.policy_audit` (cwd `src`) exits 0 / 1 and `--json` stdout parses. |
| `AuditCLITest.test_tampered_file` | A saved trace edited to show a session token exits 1 with P12. |
| `RunScenariosGuardTest.test_wrong_declared_list_raises` | For every scenario, a wrong `violated` list (patched with `mock.patch.dict`) makes `run_scenario` raise `SystemExit` naming the scenario. |
| `RunScenariosGuardTest.test_order_of_declared_list_does_not_matter` | A reordered list is accepted. |
| `RunScenariosGuardTest.test_main_stops_on_mismatch` | `run_scenarios.main` stops with `SystemExit` on a mismatch. |
| `AuditOutputsTest.test_viewer_has_flag_css_hook` | `viewer.html` defines `.ev.flag` and adds the `flag` class to flagged events. |
| `AuditOutputsTest.test_viewer_embeds_policy_audit_data` | `viewer.html` carries `policy_audit` with every violated policy. |
| `AuditOutputsTest.test_json_traces_store_findings` | Each written JSON trace has `meta.policy_audit` matching `violated`. |
| `AuditOutputsTest.test_episodes_have_audit_section` | Each episode has "## Offline Policy Audit" naming the violated policies, or "no violations". |
| `AuditOutputsTest.test_readme_has_matrix` | `traces/README.md` has the "Auditor: violated at step" column and a row for each of P1..P17. |

Auditor edge cases (class `AuditorEdgeCasesTest`; the first version of the auditor got these wrong, now regression tests):

| Test | What the auditor does | Earlier bug |
|---|---|---|
| `test_amount_equal_to_pin_is_not_a_leak` | Does not report P2 when a later message says "Send $1234 …" (an amount, deliberately left unmasked). | false positive |
| `test_pin_in_first_message_is_flagged` | Reports P2 when the PIN leaks in the first message of a conversation. | false negative |
| `test_unmasked_pin_in_saved_authenticate_message_is_flagged` | Reports P2 when the saved `authenticate` message or `verify_identity` args show the PIN unmasked. | false negative |
| `test_unmasked_pin_in_tool_result_is_flagged` | Reports P2 when a tool result contains an unmasked `pin` field. | false negative |
| `test_request_after_failed_login_in_later_conversation` | Reports P1 when a request is sent in a conversation whose login failed, even though someone logged in earlier in the trace. | false negative |

## Expected failures

The run shows 14 expected failures, all for known Phase 1 gaps.

### Known Phase 1 gaps (14 tests)

Phase 1 is the prototype **without** safety enforcement. Two gaps are left in
on purpose and marked `PHASE-1 GAP` in `src/bankassist/agents.py`. They show
up in three scenarios:

1. **P5 / P6: no ownership check on reads.** AccountAgent reads any account ID
   it is given, so Bob can read Alice's transactions (scenario `s5`).
2. **P8 / P9: express path.** When the customer asks to skip the review, the
   Concierge sends the transfer straight to AccountAgent with
   `approval_id=None`. RiskAgent and the YES/NO step are skipped, and
   AccountAgent does not validate approvals at all (scenario `s6`).
3. **P5 / P6: no ownership check on debits.** Because of the same missing
   check, Alice can move $500 out of Bob's account into her own. RiskAgent
   approves it, since the destination is her own account, and the reply shows
   her Bob's new balance (scenario `s7`).

The tests in `CrossAccountAccessPolicyTest`, `SkipReviewPolicyTest` and
`DebitOtherCustomerPolicyTest` assert the **correct** policy behaviour. They
fail today, so each one is decorated with `@unittest.expectedFailure` and
commented *"Known Phase 1 gap - to be enforced in Phase 2"*.

When Phase 2 closes a gap, the matching tests start passing. They then show up
as **unexpected successes**, which make the run fail. That is the reminder to
remove the decorator, so these tests become ordinary regression tests.

To keep the suite honest, `Phase1KnownBehaviourTest` uses normal assertions to
confirm that the leak, the bypass and the debit really happen today. In Phase 2
these tests will fail on purpose and should be removed or inverted at the same
time as the decorators.

Both `unittest` and `pytest` count expected failures as passing
(`expected failures=14` / `14 xfailed`).
