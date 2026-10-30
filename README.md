![tests](https://github.com/CrillyPienaah/governanceops-prooflab/actions/workflows/tests.yml/badge.svg)

# GovernanceOps ProofLab

Tests whether an AI agent obeyed its approved boundaries, judged by an independent ledger of what actually happened rather than by what the agent reports. See [SPEC.md](SPEC.md) for the contract schema and the three control experiments, and [docs/dogwood-findings.md](docs/dogwood-findings.md) for the Dogwood adapter's tested behaviour.

```bash
pip install -r requirements.txt pytest
pytest
python run_demo.py
```
