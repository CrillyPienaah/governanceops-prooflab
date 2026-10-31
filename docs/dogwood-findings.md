# Dogwood findings for the Week 2 adapter

**Tested version:** dogwood-py 0.0.12 (unofficial Python SDK, PyO3 binding to the Dogwood Rust reference interpreter), pinned in `requirements.txt`. Its README says the reference interpreter is not intended for production use. Re-check every rule below after any version change.

**Method:** each conclusion comes from a minimal probe: a policy, a hand-written event sequence, and an expected decision written down before the run. Probe IDs (P01–P12d) are cited for traceability. The probe files themselves stay in the untracked `scratch/` directory. "Replay" means `dogwood.native.replay` over a trace; "native" means `dogwood.native.NativeAuthorizer.authorize_request`, which is the path an adapter uses.

## 1. Native-call rules

| Rule | Evidence |
|---|---|
| Pass action IDs **unquoted**: `Payments::Action::Payout`. The quoted form `Payments::Action::"Payout"` returns `'Deny'` with no error, even under an unconditional permit. Trace files use the quoted form, which replay accepts. Reported to the dogwood-py maintainer by email on 2026-10-30. The SDK's GitHub repository (abhishektiwari/dogwood-py) returns 404, and upstream dogwood-policy/dogwood does not accept bug reports. Root cause: the native wrapper passes the action ID unchanged at `rust/src/lib.rs:146` (0.0.12 sdist). | P12a vs P12d |
| `authorize_request` returns only the string `'Allow'` or `'Deny'`: no diagnostics, rule IDs, error text or stderr output. A Deny caused by an evaluation error or a malformed call looks the same as a policy Deny. | P12a–c |
| Neither replay nor native refuses a policy that `validate_policy` rejects; both run it. | P08a, P08a-n |
| The single `input` dict fills both `context.input` (read by `when` clauses) and the recorded event fields (read by temporal patterns). | P09-u, P11-n |
| A custom event schema is accepted, including `max_window = 200d`, which raises the default 24h window cap. | P08b, P08c-u |
| `NativeAuthorizer` exposes only `authorize_request`. It doesn't expose the loaded policy, its history or any hash. | introspection |

## 2. How the PAY-042 controls are expressed (verified)

- **Tools:** both `issue_refund` and `credit_adjustment` map to one action, `Payout`, with `input.tool`. Amounts are integer cents (`Long`), so CAD 500 is `50000`.
- **Per-call cap and payee allow-list:** a `when { context.input.amount <= 50000 && [...].contains(context.input.payee) }` clause (P11, P11-n).
- **CUM-001:** `sum_within(amount, 1d, Payout::request{input.amount: amount}) == total && total <= 50000`. The sum includes the request being decided and doesn't merge equal amounts. Two 300 requests sum to 600, so the second is denied (P01, P09-u).
- **HITL-200:** approval is a prior `ApprovePayout` request matched with `formerly within 1d` on action_id, amount, payee and approval_id (P03). Single use comes from requiring that the count of `Payout` requests carrying the approval_id `== 1`, which blocks an exact replay (P04).
- **Revocation:** a `!RevokeAuthority::request{contract_id} since within W GrantAuthority::request{contract_id}` clause blocks payouts after a revoke (P07). A window longer than 24h needs a `max_window` raise in the event schema (P08b, P08c-u).

## 3. Adapter requirements

1. Call `validate_policy` at startup and refuse to run if it fails. Dogwood won't refuse for you (P08a, P08a-n).
2. Pass action IDs unquoted, and run a startup self-test: one action the policy permits must return `'Allow'`. A wrong action format or a broken setup otherwise shows up only as a blanket Deny (P12a–d).
3. Treat every `'Deny'` as unexplained. The reason is unavailable, so the adapter's denial reason can only say that Dogwood denied the call.
4. Read `registry.get().status` before each `act` and send a `RevokeAuthority` event when it's revoked. Dogwood enforces revocation only after it's told; it can't watch the registry.
5. Send `GrantAuthority` once, at startup, under an event schema whose `max_window` covers the contract's validity period.
6. Write the independent ledger only on `'Allow'`.
7. `deployed_policy_hash()` returns `None` (no equivalent), so DRIFT-001's best result is INCONCLUSIVE.
8. Dogwood has no audit log, so the agent's self-reported total is the adapter's own count of Allows. ProofLab verdicts must keep coming from the IndependentLedger.
9. Run a second startup self-test: one call the policy forbids must return `'Deny'`. Together with requirement 2 this shows the policy is actually deciding, not allowing or denying everything. Run both self-tests on a throwaway authorizer so their events never enter the real history, where a self-test payout would use up budget (P02).
10. Approval events (`ApprovePayout`) are injected only by the test harness, never by the agent. The agent-side `act` path sends only `Payout` (and `RevokeAuthority` on a registry change). Dogwood can't tell who wrote an approval (P05, P06), so this separation is the only thing that keeps approvals honest.

ProofLab's `always_deny` positive control is the scenario-level backstop for requirements 2, 3 and 9: an adapter that blocks everything FAILs for over-enforcement instead of PASSing.

## 4. Limitations

- **Denied requests use up the budget (P02).** A request stays in history whether or not it was allowed, so `sum_within` counts blocked attempts. After a denied 300, a later 100 is denied even though only 300 executed. Excluding denied requests would need an outcome event, and the native call can only send `request` events. CUM-001 makes two calls, so it doesn't reveal this, but a longer session would over-enforce.
- **Approvals and principals are whatever the caller says (P05, P06).** A denied `ApprovePayout` the agent sent itself still satisfies the approval pattern (P05). Removing the `callerPrincipal` pin and requiring `callerPrincipal: Payments::Approver::"h1"` excludes approvals sent under the agent's principal (P06, replay only). But `authorize_request` accepts any `principal` argument, so whoever can call it can claim to be the approver. Dogwood checks which principal an event names, not who sent it. An approval's authenticity has to come from outside Dogwood.
- **Native timestamps ignore real time (P10-u).** A payout 2.5 s after a ping still satisfied a `within 1s` window. `within` windows therefore don't limit real elapsed time on the native path, and neither the 1d cumulative window nor the revocation window is enforced in real time. That's acceptable for v1, where SPEC treats one test run as one window, but it must be listed in each finding's limitations. Whether native timestamps are all 0 or the call index is unverified.
- **SDK source no longer public.** dogwood-py's source repository is no longer public. The pinned 0.0.12 release and its sdist remain available on PyPI. If the SDK becomes unmaintained, the adapter would need to call the official Rust interpreter directly.
- **Not yet verified:** P06's separate-approver rule on the native path; the native timestamp value; the trace timestamp unit; window rollover (out of scope for v1).
