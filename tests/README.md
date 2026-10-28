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

Expected result: 182 tests, all passing, with **11 expected failures** (shown as `x`
by both runners). Those 11 tests describe policies that Phase 1 does not enforce
yet; see [Expected failures](#expected-failures-known-phase-1-gaps) below.

Notes:

- `tests/_path.py` puts `<repo>/src` on `sys.path`, so `bankassist` is imported
  straight from the source tree. Each test file imports it first.
- Most tests hide the `BANKASSIST_LLM_*` environment variables, so the
  Concierge runs in rule-based mode and every run is deterministic even if
  you have an LLM configured. Only `test_llm_fallback.py` turns the LLM on,
  and it points it at a small fake server on `127.0.0.1`.
- The tests never write into the repository. `run_scenarios.main()` is always
  called with `--root <temporary directory>`, and the generated files are
  deleted afterwards.
- Checks that should hold for every scripted scenario loop over
  `scenarios.SCENARIOS` instead of naming scenario IDs, so adding or renaming
  a scenario does not need a test change. The policy-gap tests find "their"
  scenario by its `violation` flag and policy list (for example the violation
  scenario that lists P5).

## Files

| File | What it covers |
|---|---|
| `_path.py` | Adds `src/` to `sys.path`; `rules_only_env()` and `RulesOnlyTestCase` hide the LLM env vars. |
| `_helpers.py` | Trace helpers (filter events, actions and messages; split a trace into turns), the P4 tool table, the P11 field set and the PIN leak scanner. |
| `test_rule_parser.py` | The Concierge's rule-based parser `rule_parse`. |
| `test_bank_tools.py` | The mock bank tools in `bank.py`, called directly. |
| `test_agents_flow.py` | End-to-end conversations through `BankAssistApp`, plus policy checks over every scripted scenario. |
| `test_policy_gaps.py` | The policies Phase 1 leaves unenforced (P5/P6, P8/P9): expected failures plus tests that record what Phase 1 does today. |
| `test_llm_fallback.py` | The optional LLM Concierge against a fake OpenAI-compatible server, the fallback to rules, and the LLM-related regression tests. |
| `test_regressions.py` | Regression tests for the bugs found by the first version of this suite (one class per fix). |
| `test_traces.py` | `run_scenarios` output (traces, episodes, README, viewer) and the `Tracer` class. |

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
| `BalanceAndHistoryTest.test_unknown_account` | A missing account gives a polite error. | – |
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
| `TransferFlowTest.test_insufficient_funds_not_reported_as_success` | A failed transfer is reported as failed ("No money was moved"). | P10, P14 |
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
| `test_risk_agent_payload_is_minimal` | `assess_transfer` carries exactly `customer_id, from_account, to_account, amount`; the follow-up `confirm_transfer` carries only `ref, customer_confirmed`; never a session token or PIN. | P11 |
| `test_concierge_never_calls_banking_tools` | ConciergeAgent's only action is `parse_request`. | P4, P12 |
| `test_each_agent_only_calls_its_own_tools` | Every action is in that agent's allowed tool set, and `record_audit` is always written under the caller's own name. | P4 |
| `test_only_account_agent_moves_money` | Every `transfer_funds` call comes from AccountAgent. | P7 |
| `test_session_token_never_shown_to_user` | No response contains `sess_`. | P12 |
| `test_account_and_risk_requests_only_after_authentication` | No message to AccountAgent or RiskAgent before a `verified` authenticate reply. | P1 |
| `test_audit_log_covers_logins_reads_denials_transfers` | Audit counts match the trace: one login entry per `verify_identity`, one read entry per balance/transactions read, one `transfer_denied` per denial, one `transfer` per `transfer_funds`. | P13 |
| `test_money_moved_only_reported_after_completed` | A "Done. Sent $…" reply only appears in a turn where AccountAgent replied `completed`. | P14 |
| `test_every_trace_has_inter_agent_messages` | Every trace has messages and all six event kinds. | – |
| `test_compliant_scenarios_have_expected_outcomes` | Every turn of the compliant scenarios gets a non-empty reply. | – |

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
| `Phase1KnownBehaviourTest.test_violation_scenarios_are_flagged` | The scenarios marked `violation` are exactly the P5 and P8 ones. | – | pass |
| `Phase1KnownBehaviourTest.test_phase1_cross_account_read_leaks_alice_transactions_to_bob` | Today, Bob does see Alice's rent and pharmacy lines, and the audit log shows C002 reading ACC-1001. | P5, P6 | pass (documents the gap) |
| `Phase1KnownBehaviourTest.test_phase1_skip_review_bypasses_risk_agent_and_confirmation` | Today, the skip-review scenario never contacts RiskAgent, and `transfer_funds` runs with `approval_id=None` and completes. | P8, P9 | pass (documents the gap) |
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

Each class guards one bug found by the first version of this suite. All of
these tests failed against the code before the fixes (the guard tests marked
"guard" below check behaviour that was already correct and must stay that way).

| Class / test | What it checks | Policy |
|---|---|---|
| `EmptyAmountRegressionTest.test_rule_parse_dollar_comma_gives_no_amount` | `rule_parse("send $, to ACC-2001")` no longer crashes: amount `None`, destination kept. | – |
| `EmptyAmountRegressionTest.test_other_degenerate_amounts` | `$`, `$,,,` and `, dollars` also give amount `None`. | – |
| `EmptyAmountRegressionTest.test_chat_asks_for_amount_instead_of_crashing` | `app.chat` replies "Please tell me the amount and the destination account…" and never reaches RiskAgent. | – |
| `NormalizeRequestTest.test_non_dict_is_rejected` | `normalize_request` returns `None` for `None`, lists, strings, numbers and bools. | – |
| `NormalizeRequestTest.test_missing_or_unknown_intent_is_rejected` | Returns `None` for a missing, `None`, unknown, wrong-case or non-string intent. | – |
| `NormalizeRequestTest.test_every_known_intent_is_accepted` | All 7 documented intents are accepted. | – |
| `NormalizeRequestTest.test_output_has_rule_parse_shape` | Output has exactly the `rule_parse` keys; extra keys (`pin`, `session_token`) are dropped. | P2, P12 |
| `NormalizeRequestTest.test_skip_review_only_true_for_true_or_string_true` | `skip_review` is `True` only for `True` or the string `"true"` (any case or spacing). `"false"`, `"False"`, `1`, `"yes"`, `""`, `None` and others give `False`. | P8 |
| `NormalizeRequestTest.test_amount_strings_are_converted` | `"50"`, `"$1,200.50"`, `" 75 "`, `75` and `12.5` become floats. | – |
| `NormalizeRequestTest.test_bad_amounts_become_none` | Garbage, empty, zero, negative, bool, list and dict amounts become `None`. | P10 |
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
| `PendingCancelledOnNewRequestTest.test_new_request_tells_risk_agent_to_cancel` | A new request while a transfer is pending sends RiskAgent `confirm_transfer` with `customer_confirmed: False`. The ref leaves `RiskAgent.pending`, and a late YES does nothing. | P9 |
| `PendingCancelledOnNewRequestTest.test_cancel_happens_before_new_transfer_is_assessed` | Message order is assess → cancel → assess; only the new ref is pending, and confirming it completes. | P9 |
| `ExpiredSessionRenewalTest.test_balance_after_expiry_reauthenticates` | After forcing expiry (`issued_at -= 10_000`), a balance request still succeeds. The trace shows a second `authenticate`, one refused and one retried `get_balance`, and two `login_success` audit entries. | P1, P13 |
| `ExpiredSessionRenewalTest.test_pin_still_masked_after_renewal` | After the renewal, the PIN is still `****` everywhere in the trace and audit log, and only goes Concierge → AuthAgent. | P2, P13 |
| `ExpiredSessionRenewalTest.test_credentials_not_kept_between_turns` | The Concierge does not keep the PIN after a turn ends. | P2 |
| `ExpiredSessionRenewalTest.test_confirmation_after_expiry_still_completes` | A YES sent after the session expired still completes the approved transfer. | P1, P14 |
| `ExpiredSessionRenewalTest.test_expiry_with_wrong_pin_returns_no_data` | If renewal fails (wrong PIN), no data is returned, the failure is counted, and the session is dropped. | P1, P3 |
| `SameAccountTransferTest.test_same_account_id_refused_without_risk_agent` | "Send $10 from ACC-1001 to ACC-1001" is refused without contacting RiskAgent or moving money. | P10 |
| `SameAccountTransferTest.test_same_account_type_refused` | "from checking to checking" is refused the same way. | P10 |
| `SameAccountTransferTest.test_same_account_with_skip_review_also_refused` | The same-account check also runs before the skip-review shortcut. | P8 |

### `test_traces.py`

`GeneratedTracesTest` runs `run_scenarios.main(["--root", tmpdir])` once,
with stdout captured.

| Class / test | What it checks | Policy |
|---|---|---|
| `GeneratedTracesTest.test_course_requirement_at_least_three_traces` | At least 3 traces are produced (course requirement). | – |
| `GeneratedTracesTest.test_one_json_and_one_md_per_scenario` | 6 scenarios, giving 6 `.json` and 6 `.md` files named after the scenario IDs. | – |
| `GeneratedTracesTest.test_readme_written` | `traces/README.md` mentions every scenario. | – |
| `GeneratedTracesTest.test_episodes_written` | `example1.md` to `example6.md`, each with the required sections. | – |
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
| `TracerUnitTest.test_redact_masks_pin_recursively` | `redact` masks nested `pin` fields and leaves the input untouched. | P2 |
| `TracerUnitTest.test_events_are_redacted_when_recorded` | Messages and actions are masked as they are recorded. | P2 |
| `TracerUnitTest.test_unknown_kind_rejected` | Only the six event kinds are accepted. | – |
| `TracerUnitTest.test_save_json_and_markdown` | Save round-trip; `|` is escaped in Markdown cells. | – |

## Expected failures (known Phase 1 gaps)

Phase 1 is the prototype **without** safety enforcement. Two gaps are left in
on purpose and marked `PHASE-1 GAP` in `src/bankassist/agents.py`:

1. **P5 / P6: no ownership check.** AccountAgent reads any account ID it is
   given, so Bob can read Alice's transactions (scenario `s5`).
2. **P8 / P9: express path.** When the customer asks to skip the review, the
   Concierge sends the transfer straight to AccountAgent with
   `approval_id=None`. RiskAgent and the YES/NO step are skipped, and
   AccountAgent does not validate approvals at all (scenario `s6`).

The tests in `CrossAccountAccessPolicyTest` and `SkipReviewPolicyTest` assert
the **correct** policy behaviour. They fail today, so each one is decorated
with `@unittest.expectedFailure` and commented *"Known Phase 1 gap - to be
enforced in Phase 2"*. Both `unittest` and `pytest` count them as passing
(`expected failures=11` / `11 xfailed`).

When Phase 2 closes a gap, the matching tests start passing. They then show up
as **unexpected successes**, which make the run fail. That is the reminder to
remove the decorator, so these tests become ordinary regression tests.

To keep the suite honest, `Phase1KnownBehaviourTest` uses normal assertions to
confirm that the leak and the bypass really happen today. In Phase 2 these
tests will fail on purpose and should be removed or inverted at the same time
as the decorators.
