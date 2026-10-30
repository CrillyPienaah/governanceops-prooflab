"""Adapter: runs the ProofLab experiments against a real governanceops-agent AgentGovernor.

The adapter only translates calls and plays the payment rail: it writes the
independent ledger when, and only when, the governor allows an action. It
enforces nothing itself, so every block must come from governanceops-agent.

Fixed inputs (agreed 2026-10-30):
  confidence = 1.0       the confidence gate never decides a verdict
  autonomy   = contract  the contract's own tier, never a higher claim
  deployed_policy_hash() returns None: the governor's hash uses Inventory's
  scheme and can't be compared with GovernanceContract.policy_hash().

Cumulative limits and approval thresholds are configured here from the
contract because Inventory's runtime-policy bundle can't express them yet.
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from governanceops_agent import (AgentGovernor, AutonomyLevel, CumulativeLimit, KillSwitchEngagedError,
                                 build_governance_from_bundle)

from fixtures.toy_agent import AgentResult, AuthorityRegistry
from prooflab.contract import GovernanceContract
from prooflab.ledger import IndependentLedger

CONFIDENCE = 1.0


def bundle_from_contract(c: GovernanceContract) -> dict:
    """The Inventory runtime-policy bundle this contract would produce.
    Only fields the bundle can express are mapped; the rest is the agent's gap."""
    limits = {g.max_per_call for g in c.tools if g.max_per_call is not None}
    if len(limits) > 1:
        raise ValueError("governanceops-agent has one transaction_limit for all tools")
    return {
        "ai_system_name": c.agent_id,
        "autonomy_level": AutonomyLevel(int(c.autonomy_level)).name.lower(),
        "permitted_tools": [g.name for g in c.tools],
        "forbidden_tools": [],
        "confidence_threshold": None,
        "transaction_limit": float(limits.pop()) if limits else None,
    }


class GovernanceOpsAgentAdapter:
    def __init__(self, registry: AuthorityRegistry, ledger: IndependentLedger,
                 secret_key: str = "prooflab-adapter-not-for-production") -> None:
        self.registry, self.ledger = registry, ledger
        contract = registry.get()                      # policy read once, as from_governanceops() does
        compiled = build_governance_from_bundle(bundle_from_contract(contract))
        self.governor = AgentGovernor(secret_key=secret_key, policy_engine=compiled.engine,
                                      authority_check=lambda: registry.get().status == "active")
        thresholds = {t: float(r.threshold) for r in contract.approval_rules for t in r.tools}
        for scope in compiled.tool_scopes:
            self.governor.permissions.register(replace(scope, approval_above=thresholds.get(scope.tool_name)))
        for lim in contract.cumulative_limits:
            self.governor.permissions.register_cumulative_limit(
                CumulativeLimit(lim.limit_id, lim.tools, float(lim.ceiling)))
        self.autonomy = AutonomyLevel(int(contract.autonomy_level))

    # ---- AgentUnderTest interface ----------------------------------------
    def deployed_policy_hash(self) -> str | None:
        return None

    def request_approval(self, action_id: str, tool: str, amount: Decimal, payee: str) -> str | None:
        """Asks the governor for a checkpoint bound to this exact call; the
        simulated human approves it, as the toy agent's approver does."""
        params = {"action_id": action_id, "amount": amount, "payee": payee}
        cp = self.governor.request_approval(tool, tool, params)
        if cp is None:
            return None
        self.governor.checkpoints.approve(cp.checkpoint_id, approver="prooflab-approver")
        return cp.checkpoint_id

    def act(self, action_id: str, tool: str, amount: Decimal, payee: str,
            approval_id: str | None = None) -> AgentResult:
        params = {"action_id": action_id, "amount": amount, "payee": payee}
        try:
            out = self.governor.evaluate_action(tool, CONFIDENCE, self.autonomy, tool_name=tool,
                                                tool_params=params, approval_checkpoint_id=approval_id)
        except KillSwitchEngagedError as exc:
            return AgentResult(False, str(exc), self._reported())
        if not out.allowed:
            reason = out.denial_reason or f"approval required (checkpoint {out.checkpoint.checkpoint_id})"
            return AgentResult(False, reason, self._reported())
        self.ledger.record(tool, amount, payee, approval_id)
        return AgentResult(True, "executed", self._reported())

    # ---- internals --------------------------------------------------------
    def _reported(self) -> Decimal:
        # What the agent's own audit log says it allowed: its self-report.
        return sum((Decimal(str(e.payload["params"]["amount"]))
                    for e in self.governor.audit_log.entries if e.event_type == "tool_call_allowed"),
                   Decimal(0))
