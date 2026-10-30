"""Inventory record -> contract: inventory-sourced fields round-trip, unsourced ones are never invented.
Runs under pytest, or directly: python -m tests.test_from_inventory
"""
from dataclasses import fields

from prooflab.contract import GovernanceContract
from prooflab.from_inventory import (INVENTORY_SOURCE, NO_INVENTORY_SOURCE, MissingContractFields,
                                     contract_from_inventory, inventory_fields_from_contract)
from tests.test_controls import CONTRACT


def unsourced_of(c):
    return {k: getattr(c, k) for k in NO_INVENTORY_SOURCE}


def test_every_contract_field_is_sourced_or_listed_as_unsourced():
    names = {f.name for f in fields(GovernanceContract)}
    assert names == set(INVENTORY_SOURCE) | set(NO_INVENTORY_SOURCE)
    assert not set(INVENTORY_SOURCE) & set(NO_INVENTORY_SOURCE)


def test_pay_042_round_trips_through_an_inventory_record():
    record = inventory_fields_from_contract(CONTRACT)
    assert not set(record) & set(NO_INVENTORY_SOURCE), "record carries a field the inventory doesn't have"
    assert record["transaction_limit"] == 500.0 and record["autonomy_level"] == "l2_human_on_loop"
    rebuilt = contract_from_inventory(record, unsourced_of(CONTRACT))
    assert rebuilt == CONTRACT
    assert rebuilt.policy_hash() == CONTRACT.policy_hash()


def test_unsourced_fields_are_required_not_defaulted():
    record = inventory_fields_from_contract(CONTRACT)
    try:
        contract_from_inventory(record, {})
    except MissingContractFields as exc:
        for name in NO_INVENTORY_SOURCE:
            assert name in str(exc)
    else:
        raise AssertionError("built a contract with no values for the unsourced fields")


def test_inventory_sourced_fields_cannot_be_overridden():
    record = inventory_fields_from_contract(CONTRACT)
    try:
        contract_from_inventory(record, {**unsourced_of(CONTRACT), "risk_rating": "low"})
    except ValueError as exc:
        assert "risk_rating" in str(exc)
    else:
        raise AssertionError("caller overrode the inventory's risk rating")


def test_record_without_autonomy_level_has_no_contract():
    record = {**inventory_fields_from_contract(CONTRACT), "autonomy_level": None}
    try:
        contract_from_inventory(record, unsourced_of(CONTRACT))
    except ValueError as exc:
        assert "autonomy_level" in str(exc)
    else:
        raise AssertionError("built a contract for a model with no runtime policy")


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok   {name}")
    print(f"\n{len(tests)} passed")
