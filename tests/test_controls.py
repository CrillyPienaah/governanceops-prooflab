"""Each seeded fault must FAIL; the fixed agent must PASS; missing observation must be INCONCLUSIVE.
Runs under pytest, or directly: python -m tests.test_controls
"""
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from fixtures.toy_agent import AuthorityRegistry, ToyPaymentsAgent
from prooflab.contract import CumulativeLimit, GovernanceContract
from prooflab.evidence import Verdict
from prooflab.ledger import IndependentLedger
from prooflab.scenarios import apr_001, bundle, cum_001, drift_001

CONTRACT = GovernanceContract.from_json(Path(__file__).parent.parent / "contracts" / "pay-042.json")
CLOCK = datetime(2026, 11, 15, tzinfo=timezone.utc)
KEY = b"demo-key-not-for-production"


def make_env(faults=(), deployed=None):
    reg, led = AuthorityRegistry(CONTRACT), IndependentLedger()
    agent = ToyPaymentsAgent(reg, led, CLOCK, frozenset(faults), deployed)
    return agent, reg, led


# ---- CUM-001: cumulative limit across tools --------------------------------
def test_cum_detects_per_tool_enforcement():
    agent, _, led = make_env({"per_tool_limit"})
    f = cum_001(agent, CONTRACT, led)
    assert f.verdict is Verdict.FAIL
    assert f.agent_reported["reported_cumulative"] == "300"
    assert f.ledger_observed["ledger_total"] == "600"

def test_cum_passes_when_enforced_across_tools():
    agent, _, led = make_env()
    assert cum_001(agent, CONTRACT, led).verdict is Verdict.PASS


# ---- APR-001: approval reuse ------------------------------------------------
def test_apr_detects_reused_approval():
    agent, _, led = make_env({"approval_reuse"})
    f = apr_001(agent, CONTRACT, led)
    assert f.verdict is Verdict.FAIL
    assert len(f.ledger_observed["reused_approval_ids"]) == 1

def test_apr_passes_with_single_use_bound_approvals():
    agent, _, led = make_env()
    assert apr_001(agent, CONTRACT, led).verdict is Verdict.PASS


# ---- DRIFT-001: stale authority and policy drift ---------------------------
def test_drift_detects_stale_revocation_cache():
    agent, reg, led = make_env({"stale_authority"})
    f = drift_001(agent, CONTRACT, reg, led)
    assert f.verdict is Verdict.FAIL and "after revocation" in f.observed

def test_drift_detects_unapproved_deployed_policy():
    loosened = replace(CONTRACT, cumulative_limits=(
        CumulativeLimit("CUM-CAD-500", ("issue_refund", "credit_adjustment"), "CAD", Decimal("1000"), "PT24H"),))
    agent, reg, led = make_env(deployed=loosened)
    f = drift_001(agent, CONTRACT, reg, led)
    assert f.verdict is Verdict.FAIL and "differs" in f.observed

def test_drift_passes_when_current_and_matching():
    agent, reg, led = make_env()
    assert drift_001(agent, CONTRACT, reg, led).verdict is Verdict.PASS


# ---- Positive control: blocking everything is not compliance ----------------
def test_no_scenario_passes_when_agent_denies_everything():
    runs = {"CUM-001": lambda a, r, l: cum_001(a, CONTRACT, l),
            "APR-001": lambda a, r, l: apr_001(a, CONTRACT, l),
            "DRIFT-001": lambda a, r, l: drift_001(a, CONTRACT, r, l)}
    for name, run in runs.items():
        agent, reg, led = make_env({"always_deny"})
        f = run(agent, reg, led)
        assert f.verdict is not Verdict.PASS, f"{name} passed an agent that blocks everything: {f.observed}"


# ---- Observation and evidence integrity ------------------------------------
def test_no_ledger_means_inconclusive_never_pass():
    agent, _, led = make_env()
    led.available = False
    assert cum_001(agent, CONTRACT, led).verdict is Verdict.INCONCLUSIVE

def test_tampered_evidence_fails_verification():
    agent, _, led = make_env({"per_tool_limit"})
    b = bundle(CONTRACT, led, [cum_001(agent, CONTRACT, led)], KEY)
    assert b.verify(KEY)
    b.findings[0].verdict = Verdict.PASS          # someone edits the result
    assert not b.verify(KEY)

def test_ledger_chain_intact():
    agent, _, led = make_env()
    cum_001(agent, CONTRACT, led)
    assert led.chain_intact()


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok   {name}")
    print(f"\n{len(tests)} passed")
