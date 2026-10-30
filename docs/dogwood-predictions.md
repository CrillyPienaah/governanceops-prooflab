# Dogwood adapter: predicted verdicts

Written 2026-10-30, before `tests/test_dogwood_adapter.py` was first run, against `policies/pay-042.dw` on dogwood-py 0.0.12. The policy wasn't changed after this file was written.

| Check | Predicted | Reasoning |
|---|---|---|
| CUM-001 | **PASS** | The first 300 sums to 30000 cents ≤ 50000 with a bound approval, so it's allowed. The second 300 sums to 60000, because the sum includes the current request (P01), so it's denied. The ledger total is 300 and the first action executed. |
| APR-001 | **PASS** | A1's approval matches action_id, amount, payee and approval_id, so it's allowed. A2 reuses the token with a different action and payee, so no ApprovePayout event matches and it's denied (P03). Only one ledger entry carries the approval. |
| DRIFT-001 | **INCONCLUSIVE** | The pre-revocation control (100, under the 200 threshold, within budget) is allowed, giving one ledger entry. After `registry.revoke()` the adapter sends RevokeAuthority, so the next payout fails the "no revoke since grant" clause (P07, P08c-u), giving zero entries after revocation. `deployed_policy_hash()` is None, so the verdict can't be PASS. |
| always_deny check | **Raises DogwoodStartupError at startup** | With a policy that denies every payout, the known-permitted self-test returns 'Deny', so `DogwoodRuntime` refuses to start. No scenario runs, so none can PASS. The adapter can never be in the always-deny state that ProofLab's `always_deny` control simulates in the toy agent. |
