"""The three v1 experiments against a Dogwood-policied agent, plus the adapter's own guarantees.
Skipped cleanly when dogwood-py (or its native extension) isn't installed.
"""
from dataclasses import replace
from decimal import Decimal

import pytest

pytest.importorskip("dogwood")
from dogwood import native  # noqa: E402

if not native.available():
    pytest.skip("dogwood-py native extension unavailable", allow_module_level=True)

from fixtures.dogwood_adapter import (APPROVE, DogwoodAdapter, DogwoodRuntime, DogwoodStartupError,  # noqa: E402
                                      HarnessApprover, MockPaymentRail, to_cents)
from fixtures.toy_agent import AuthorityRegistry  # noqa: E402
from prooflab.contract import CumulativeLimit  # noqa: E402
from prooflab.evidence import Verdict  # noqa: E402
from prooflab.ledger import IndependentLedger  # noqa: E402
from prooflab.scenarios import apr_001, cum_001, drift_001  # noqa: E402
from tests.test_controls import CONTRACT  # noqa: E402

DENY_ALL = """
@id("grant_only")
permit (principal, action == Payments::Action::"GrantAuthority", resource);
"""
ALLOW_ALL = """
@id("anything_goes")
permit (principal, action == Payments::Action::"Payout", resource);
"""
OVER_WINDOW = """
@id("window_over_max")
permit (principal, action == Payments::Action::"Payout", resource)
when temporal {
    formerly within 300d (
        Payments::Action::"GrantAuthority"::request{ input.contract_id: context.input.contract_id }
    )
};
"""


def make_dogwood_env():
    reg, led = AuthorityRegistry(CONTRACT), IndependentLedger()
    runtime = DogwoodRuntime(CONTRACT)
    agent = DogwoodAdapter(reg, runtime, HarnessApprover(runtime), MockPaymentRail(led))
    return agent, reg, led


# ---- The v1 experiments -----------------------------------------------------
def test_dogwood_cum_001_cumulative_limit_across_tools():
    agent, _, led = make_dogwood_env()
    f = cum_001(agent, CONTRACT, led)
    assert f.verdict is Verdict.PASS, f.observed


def test_dogwood_apr_001_approval_single_use_and_bound():
    agent, _, led = make_dogwood_env()
    f = apr_001(agent, CONTRACT, led)
    assert f.verdict is Verdict.PASS, f.observed


def test_dogwood_drift_001_revocation_honoured():
    # No deployed hash is exposed, so the best honest verdict is INCONCLUSIVE
    # with the pre-revocation control executed and nothing recorded afterwards.
    agent, reg, led = make_dogwood_env()
    f = drift_001(agent, CONTRACT, reg, led)
    assert f.ledger_observed["entries_before_revocation"] == 1, f.observed
    assert f.ledger_observed["entries_after_revocation"] == 0, f.observed
    assert f.verdict is Verdict.INCONCLUSIVE, f.observed


# ---- Startup checks: never run degraded -------------------------------------
def test_refuses_to_start_when_policy_denies_everything():
    with pytest.raises(DogwoodStartupError, match="known-permitted"):
        DogwoodRuntime(CONTRACT, policy_source=DENY_ALL)


def test_refuses_to_start_when_policy_allows_everything():
    with pytest.raises(DogwoodStartupError, match="known-forbidden"):
        DogwoodRuntime(CONTRACT, policy_source=ALLOW_ALL)


def test_refuses_to_start_when_policy_fails_validation():
    with pytest.raises(DogwoodStartupError, match="validation"):
        DogwoodRuntime(CONTRACT, policy_source=OVER_WINDOW)


def test_refuses_a_contract_the_policy_does_not_encode():
    loosened = replace(CONTRACT, cumulative_limits=(
        CumulativeLimit("CUM-CAD-500", ("issue_refund", "credit_adjustment"), "CAD", Decimal("1000"), "PT24H"),))
    with pytest.raises(DogwoodStartupError, match="cumulative limits"):
        DogwoodRuntime(loosened)


# ---- Amounts ------------------------------------------------------------------
def test_cents_conversion_is_exact_and_refuses_fractions_of_a_cent():
    assert to_cents(Decimal("300")) == 30000
    assert to_cents(Decimal("0.01")) == 1
    assert to_cents(Decimal("199.99")) == 19999
    for bad in (Decimal("0.001"), Decimal("100.005"), 100.0):
        with pytest.raises(ValueError):
            to_cents(bad)


def test_non_integer_cents_are_refused_and_never_reach_the_rail():
    agent, _, led = make_dogwood_env()
    res = agent.act("CENT-A1", "issue_refund", Decimal("100.005"), "CUST-1001")
    assert not res.executed and "cents" in res.reason
    assert led.entries() == []


# ---- Trust split: approvals come only from the harness ------------------------
def test_approval_events_are_sent_only_by_the_harness():
    agent, _, led = make_dogwood_env()
    cum_001(agent, CONTRACT, led)
    apr_001(agent, CONTRACT, led)
    approvals = [sender for sender, action in agent.runtime.sent if action == APPROVE]
    assert approvals and set(approvals) == {"harness"}
    assert all(action != APPROVE for sender, action in agent.runtime.sent if sender == "adapter")


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok   {name}")
    print(f"\n{len(tests)} passed")
