"""Demo: run all three experiments against the faulty agent, then the fixed one."""
from dataclasses import replace
from decimal import Decimal

from prooflab.contract import CumulativeLimit
from prooflab.scenarios import apr_001, bundle, cum_001, drift_001
from tests.test_controls import CONTRACT, KEY, make_env

FAULTS = {"per_tool_limit", "approval_reuse", "stale_authority"}


def run(label, faults):
    findings = []
    for scen in ("cum", "apr", "drift"):
        agent, reg, led = make_env(faults)          # fresh environment per experiment
        if scen == "cum":
            findings.append(cum_001(agent, CONTRACT, led))
        elif scen == "apr":
            findings.append(apr_001(agent, CONTRACT, led))
        else:
            findings.append(drift_001(agent, CONTRACT, reg, led))
    b = bundle(CONTRACT, led, findings, KEY)
    print(f"\n=== {label} ===")
    for f in findings:
        print(f"{f.test_id:<10} {f.verdict.value:<13} {f.observed}")
    print(f"evidence signature valid: {b.verify(KEY)}")


if __name__ == "__main__":
    run("Seeded faults", FAULTS)
    run("Remediated", set())
