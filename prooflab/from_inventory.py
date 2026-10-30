"""Build a GovernanceContract from a governanceops-inventory E-23 record.

The record is the JSON a ModelInventoryRecord serialises to (GET /models/{id}):
the 17 Appendix 1 fields plus the runtime-policy extensions. Stdlib only, so
the record arrives as a dict rather than the inventory's Pydantic model.

Only some contract fields have a source in that schema. The rest are listed
in NO_INVENTORY_SOURCE and must be supplied by the caller; nothing is defaulted.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from prooflab.contract import AutonomyLevel, GovernanceContract, ToolGrant

# Contract field -> where it comes from in the inventory record.
INVENTORY_SOURCE = {
    "agent_id": "model_id",
    "inventory_record_id": "record_id",
    "risk_rating": "model_risk_rating",
    "autonomy_level": "autonomy_level",
    "tools": "permitted_tools, each capped at transaction_limit",
}

# Contract fields the inventory schema cannot supply, and why.
NO_INVENTORY_SOURCE = {
    "contract_id": "the inventory has no contract identity",
    "policy_version": "the record has none; policy_version is only on the runtime-policy "
                      "bundle and the ORM row, as an int",
    "cumulative_limits": "no field for a ceiling across several tools",
    "approval_rules": "no amount threshold for human approval; confidence_threshold is a "
                      "confidence gate, not an amount",
    "allowed_payees": "no destination allow-list",
    "valid_from": "no approval-validity start; deployment_date is when it went live, not "
                  "when authority starts",
    "valid_until": "no approval expiry; next_review_date is a review deadline, not an expiry",
    "status": "no revoked state; monitoring_status and exemption status mean other things",
}

# Inventory fields that map to nothing in the contract.
NO_CONTRACT_DESTINATION = ("forbidden_tools", "confidence_threshold")

# The inventory's AutonomyLevel values, which mirror the L0-L4 scale.
_INVENTORY_AUTONOMY = {
    AutonomyLevel.L0: "l0_no_autonomy",
    AutonomyLevel.L1: "l1_human_in_loop",
    AutonomyLevel.L2: "l2_human_on_loop",
    AutonomyLevel.L3: "l3_bounded_autonomy",
    AutonomyLevel.L4: "l4_full_autonomy",
}


class MissingContractFields(ValueError):
    pass


def _decimal(x: float | int | str) -> Decimal:
    # The inventory stores transaction_limit as a float, so 500 arrives as 500.0.
    # Normalise integral values back to "500": policy_hash() hashes the string form.
    d = Decimal(str(x))
    return d.to_integral_value() if d == d.to_integral_value() else d


def contract_from_inventory(record: dict[str, Any], unsourced: dict[str, Any]) -> GovernanceContract:
    """`unsourced` must hold exactly the NO_INVENTORY_SOURCE fields, already typed."""
    missing = sorted(set(NO_INVENTORY_SOURCE) - set(unsourced))
    if missing:
        raise MissingContractFields(f"no inventory source and not supplied: {', '.join(missing)}")
    extra = sorted(set(unsourced) - set(NO_INVENTORY_SOURCE))
    if extra:
        raise ValueError(f"these come from the inventory record and can't be overridden: {', '.join(extra)}")

    if not record.get("autonomy_level"):
        raise ValueError(f"{record['model_id']} has no autonomy_level, so no runtime policy to contract")
    overlap = set(record.get("permitted_tools") or ()) & set(record.get("forbidden_tools") or ())
    if overlap:
        raise ValueError(f"tools both permitted and forbidden: {', '.join(sorted(overlap))}")

    limit = record.get("transaction_limit")
    cap = None if limit is None else _decimal(limit)
    return GovernanceContract(
        agent_id=record["model_id"],
        inventory_record_id=str(record["record_id"]),
        risk_rating=record["model_risk_rating"],
        autonomy_level={v: k for k, v in _INVENTORY_AUTONOMY.items()}[record["autonomy_level"]],
        tools=tuple(ToolGrant(name, cap) for name in record.get("permitted_tools") or ()),
        **unsourced,
    )


def inventory_fields_from_contract(c: GovernanceContract) -> dict[str, Any]:
    """The inventory record fields a contract implies, as the inventory API would
    serialise them. Partial: Appendix 1 fields such as model_owner aren't in a contract."""
    caps = {t.max_per_call for t in c.tools}
    if len(caps) > 1:
        raise ValueError("the inventory has one transaction_limit for all tools")
    cap = caps.pop() if caps else None
    return {
        "model_id": c.agent_id,
        "record_id": c.inventory_record_id,
        "model_risk_rating": c.risk_rating,
        "autonomy_level": _INVENTORY_AUTONOMY[c.autonomy_level],
        "permitted_tools": [t.name for t in c.tools],
        "forbidden_tools": [],
        "confidence_threshold": None,
        "transaction_limit": None if cap is None else float(cap),
    }
