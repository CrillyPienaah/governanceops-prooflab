"""Adapter: runs the ProofLab experiments against a Dogwood-policied agent.

Follows docs/dogwood-findings.md section 3 (requirements 1-10). Dogwood decides
every payout; the adapter only translates calls, tells Dogwood about registry
changes, and passes allowed payouts to the mock payment rail, the only writer of
the independent ledger. It enforces nothing itself.

Trust split (requirement 10): DogwoodRuntime sends events. The agent side
(DogwoodAdapter.act) sends only Payout and RevokeAuthority; ApprovePayout comes
only from HarnessApprover, which the test harness owns and hands to the adapter so
that AgentUnderTest.request_approval has someone to ask.

Fixed inputs:
  policies/pay-042.dw hard-codes PAY-042's limits; the adapter refuses any other
  contract rather than run a policy that doesn't match it.
  deployed_policy_hash() returns None: NativeAuthorizer exposes no policy or hash.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path

from dogwood import native

from fixtures.toy_agent import AgentResult, AuthorityRegistry
from prooflab.contract import GovernanceContract
from prooflab.ledger import IndependentLedger, LedgerEntry

POLICY_DIR = Path(__file__).resolve().parent.parent / "policies"
NAMESPACE = "Payments"
# Unquoted action IDs: the quoted form is silently denied (findings, P12a vs P12d).
PAYOUT = f"{NAMESPACE}::Action::Payout"
APPROVE = f"{NAMESPACE}::Action::ApprovePayout"
GRANT = f"{NAMESPACE}::Action::GrantAuthority"
REVOKE = f"{NAMESPACE}::Action::RevokeAuthority"
RESOURCE = f'{NAMESPACE}::Rail::"mock-rail"'
NOT_A_PAYEE = "PROOFLAB-NOT-A-PAYEE"

# What policies/pay-042.dw hard-codes, in contract units.
POLICY_TERMS = {
    "tools": {"issue_refund": Decimal("500"), "credit_adjustment": Decimal("500")},
    "cumulative": (("issue_refund", "credit_adjustment"), "CAD", Decimal("500"), "PT24H"),
    "approval": (("issue_refund", "credit_adjustment"), Decimal("200"), True,
                 ("action_id", "amount", "payee")),
    "payees": {"CUST-1001", "CUST-1002"},
    "max_validity_days": 200,
}


class DogwoodStartupError(RuntimeError):
    """A startup check failed; the adapter refuses to run degraded."""


def to_cents(amount: Decimal) -> int:
    """CAD to integer cents, exactly. Refuses anything with a fraction of a cent."""
    if isinstance(amount, float):
        raise ValueError("amounts must be Decimal or int, not float")
    cents = Decimal(amount) * 100
    if cents != cents.to_integral_value():
        raise ValueError(f"{amount} is not a whole number of cents")
    return int(cents)


def _event_input(contract_id: str, *, tool: str = "", action_id: str = "", cents: int = 0,
                 payee: str = "", approval_id: str | None = None, status: str = "") -> dict:
    return {"tool": tool, "action_id": action_id, "amount": cents, "payee": payee,
            "approval_id": approval_id or "", "contract_id": contract_id, "status": status}


def _check_contract_matches_policy(c: GovernanceContract) -> None:
    problems = []
    if {g.name: g.max_per_call for g in c.tools} != POLICY_TERMS["tools"]:
        problems.append("tools or per-call limits")
    if [(l.tools, l.currency, l.ceiling, l.window) for l in c.cumulative_limits] != [POLICY_TERMS["cumulative"]]:
        problems.append("cumulative limits")
    if [(a.tools, a.threshold, a.single_use, a.bound_fields) for a in c.approval_rules] != [POLICY_TERMS["approval"]]:
        problems.append("approval rules")
    if set(c.allowed_payees) != POLICY_TERMS["payees"]:
        problems.append("allowed payees")
    if (c.valid_until - c.valid_from).days > POLICY_TERMS["max_validity_days"]:
        problems.append("validity period longer than the policy's 200d authority window")
    if problems:
        raise DogwoodStartupError(f"contract {c.contract_id} doesn't match policies/pay-042.dw: {', '.join(problems)}")


class DogwoodRuntime:
    """One stateful NativeAuthorizer for one session, plus the startup checks."""

    def __init__(self, contract: GovernanceContract, policy_source: str | None = None) -> None:
        _check_contract_matches_policy(contract)
        self.contract_id = contract.contract_id
        self.principal = f'{NAMESPACE}::Agent::"{contract.agent_id}"'
        self._sources = (
            policy_source if policy_source is not None else (POLICY_DIR / "pay-042.dw").read_text(),
            (POLICY_DIR / "payments.cedarschema").read_text(),
            (POLICY_DIR / "payments.dwschema").read_text(),
        )
        self.sent: list[tuple[str, str]] = []      # (sender, action), for the trust-split test
        self._startup_checks()
        self._auth = native.NativeAuthorizer(*self._sources)
        self._send("adapter", GRANT, _event_input(self.contract_id, action_id="GRANT", status="active"))

    def _startup_checks(self) -> None:
        native.require_available()
        result = native.validate_policy(*self._sources)
        if not result.get("passed"):
            raise DogwoodStartupError(f"policy failed validation: {result.get('errors')}")
        # Self-tests run on a throwaway authorizer so their events never reach the
        # real history, where the test payout would use up budget (findings, P02).
        probe = native.NativeAuthorizer(*self._sources)
        probe.authorize_request(GRANT, self.principal, RESOURCE,
                                _event_input(self.contract_id, action_id="GRANT", status="active"))
        known_allow = _event_input(self.contract_id, tool="issue_refund", action_id="SELFTEST-ALLOW",
                                   cents=100, payee=sorted(POLICY_TERMS["payees"])[0], status="requested")
        known_deny = dict(known_allow, action_id="SELFTEST-DENY", payee=NOT_A_PAYEE)
        if (got := probe.authorize_request(PAYOUT, self.principal, RESOURCE, known_allow)) != "Allow":
            raise DogwoodStartupError(f"known-permitted payout returned {got!r}, expected 'Allow'")
        if (got := probe.authorize_request(PAYOUT, self.principal, RESOURCE, known_deny)) != "Deny":
            raise DogwoodStartupError(f"known-forbidden payout returned {got!r}, expected 'Deny'")

    def _send(self, sender: str, action: str, event_input: dict) -> str:
        decision = self._auth.authorize_request(action, self.principal, RESOURCE, event_input)
        if decision not in ("Allow", "Deny"):
            raise RuntimeError(f"unexpected Dogwood decision {decision!r}")
        self.sent.append((sender, action))
        return decision

    # Agent side.
    def payout(self, event_input: dict) -> str:
        return self._send("adapter", PAYOUT, event_input)

    def revoke(self) -> None:
        self._send("adapter", REVOKE, _event_input(self.contract_id, action_id="REVOKE", status="revoked"))

    # Harness side; called only by HarnessApprover.
    def _inject_approval(self, event_input: dict) -> None:
        self._send("harness", APPROVE, event_input)


class HarnessApprover:
    """The simulated human approver. Owned by the test harness, never by the agent."""

    def __init__(self, runtime: DogwoodRuntime) -> None:
        self._runtime = runtime

    def approve(self, action_id: str, tool: str, amount: Decimal, payee: str) -> str:
        approval_id = f"APR-{uuid.uuid4().hex[:8]}"
        self._runtime._inject_approval(_event_input(
            self._runtime.contract_id, tool=tool, action_id=action_id, cents=to_cents(amount),
            payee=payee, approval_id=approval_id, status="approved"))
        return approval_id


class MockPaymentRail:
    """Moves the money, so it alone writes the independent ledger."""

    def __init__(self, ledger: IndependentLedger) -> None:
        self._ledger = ledger

    def execute(self, tool: str, amount: Decimal, payee: str, approval_id: str | None) -> LedgerEntry:
        return self._ledger.record(tool, amount, payee, approval_id)


class DogwoodAdapter:
    def __init__(self, registry: AuthorityRegistry, runtime: DogwoodRuntime,
                 approver: HarnessApprover, rail: MockPaymentRail) -> None:
        self.registry, self.runtime, self.rail = registry, runtime, rail
        self._approver = approver
        self._revocation_sent = False
        self._allowed: list[Decimal] = []

    # ---- AgentUnderTest interface ----------------------------------------
    def deployed_policy_hash(self) -> str | None:
        return None

    def request_approval(self, action_id: str, tool: str, amount: Decimal, payee: str) -> str:
        return self._approver.approve(action_id, tool, amount, payee)

    def act(self, action_id: str, tool: str, amount: Decimal, payee: str,
            approval_id: str | None = None) -> AgentResult:
        if self.registry.get().status != "active" and not self._revocation_sent:
            self.runtime.revoke()
            self._revocation_sent = True
        try:
            cents = to_cents(amount)
        except ValueError as exc:
            return AgentResult(False, f"refused: {exc}", self._reported())
        decision = self.runtime.payout(_event_input(
            self.runtime.contract_id, tool=tool, action_id=action_id, cents=cents, payee=payee,
            approval_id=approval_id, status="requested"))
        if decision != "Allow":
            return AgentResult(False, "Dogwood denied (no reason available)", self._reported())
        self.rail.execute(tool, amount, payee, approval_id)
        self._allowed.append(amount)
        return AgentResult(True, "executed", self._reported())

    # ---- internals --------------------------------------------------------
    def _reported(self) -> Decimal:
        # The adapter's own count of Allows: a self-report, never a verdict source.
        return sum(self._allowed, Decimal(0))
