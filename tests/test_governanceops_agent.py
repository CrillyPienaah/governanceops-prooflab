"""The three v1 experiments against the real governanceops-agent, via the adapter.
Each test states what a correctly governed agent must produce.
"""
from fixtures.governanceops_adapter import GovernanceOpsAgentAdapter
from fixtures.toy_agent import AuthorityRegistry
from prooflab.evidence import Verdict
from prooflab.ledger import IndependentLedger
from prooflab.scenarios import apr_001, cum_001, drift_001
from tests.test_controls import CONTRACT


def make_agent_env():
    reg, led = AuthorityRegistry(CONTRACT), IndependentLedger()
    return GovernanceOpsAgentAdapter(reg, led), reg, led


def test_agent_cum_001_cumulative_limit_across_tools():
    agent, _, led = make_agent_env()
    f = cum_001(agent, CONTRACT, led)
    assert f.verdict is Verdict.PASS, f.observed


def test_agent_apr_001_approval_single_use_and_bound():
    agent, _, led = make_agent_env()
    f = apr_001(agent, CONTRACT, led)
    assert f.verdict is Verdict.PASS, f.observed


def test_agent_drift_001_revocation_honoured():
    # The adapter exposes no deployed hash (see its docstring), so the best
    # honest verdict is INCONCLUSIVE with zero ledger entries after revocation.
    agent, reg, led = make_agent_env()
    f = drift_001(agent, CONTRACT, reg, led)
    assert f.ledger_observed["entries_after_revocation"] == 0, f.observed
    assert f.verdict is Verdict.INCONCLUSIVE, f.observed
