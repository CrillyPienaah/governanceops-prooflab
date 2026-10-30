"""Governance contract: what an agent is approved to do, sourced from the inventory record."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from decimal import Decimal
from enum import IntEnum
from pathlib import Path


class AutonomyLevel(IntEnum):
    L0 = 0  # no autonomous action
    L1 = 1
    L2 = 2
    L3 = 3
    L4 = 4  # fully autonomous within limits


@dataclass(frozen=True)
class ToolGrant:
    name: str
    max_per_call: Decimal | None = None


@dataclass(frozen=True)
class CumulativeLimit:
    """A ceiling across ALL listed tools combined, not per tool."""
    limit_id: str
    tools: tuple[str, ...]
    currency: str
    ceiling: Decimal
    window: str  # ISO 8601 duration; v1 treats one test run as one window


@dataclass(frozen=True)
class ApprovalRule:
    """Human approval required above a threshold; single-use and bound to one action."""
    rule_id: str
    tools: tuple[str, ...]
    threshold: Decimal
    single_use: bool = True
    bound_fields: tuple[str, ...] = ("action_id", "amount", "payee")


@dataclass(frozen=True)
class GovernanceContract:
    contract_id: str
    agent_id: str
    inventory_record_id: str      # links to the governanceops-inventory E-23 record
    risk_rating: str              # institution-defined
    autonomy_level: AutonomyLevel
    policy_version: str
    tools: tuple[ToolGrant, ...]
    cumulative_limits: tuple[CumulativeLimit, ...]
    approval_rules: tuple[ApprovalRule, ...]
    allowed_payees: tuple[str, ...]
    valid_from: datetime
    valid_until: datetime
    status: str = "active"        # "active" | "revoked"

    def canonical(self) -> str:
        def enc(o):
            if isinstance(o, Decimal):
                return str(o)
            if isinstance(o, datetime):
                return o.isoformat()
            raise TypeError(type(o))
        return json.dumps(asdict(self), default=enc, sort_keys=True, separators=(",", ":"))

    def policy_hash(self) -> str:
        """Hash of approved policy content. Status is excluded so revocation is checked separately."""
        d = json.loads(self.canonical())
        d.pop("status")
        return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()

    def is_valid_at(self, t: datetime) -> bool:
        return self.status == "active" and self.valid_from <= t <= self.valid_until

    @classmethod
    def from_json(cls, path: str | Path) -> "GovernanceContract":
        d = json.loads(Path(path).read_text())
        dt = lambda s: datetime.fromisoformat(s).astimezone(timezone.utc)
        return cls(
            contract_id=d["contract_id"],
            agent_id=d["agent_id"],
            inventory_record_id=d["inventory_record_id"],
            risk_rating=d["risk_rating"],
            autonomy_level=AutonomyLevel[d["autonomy_level"]],
            policy_version=d["policy_version"],
            tools=tuple(ToolGrant(t["name"], Decimal(t["max_per_call"]) if t.get("max_per_call") else None)
                        for t in d["tools"]),
            cumulative_limits=tuple(CumulativeLimit(c["limit_id"], tuple(c["tools"]), c["currency"],
                                                    Decimal(c["ceiling"]), c["window"])
                                    for c in d["cumulative_limits"]),
            approval_rules=tuple(ApprovalRule(a["rule_id"], tuple(a["tools"]), Decimal(a["threshold"]),
                                              a.get("single_use", True),
                                              tuple(a.get("bound_fields", ("action_id", "amount", "payee"))))
                                 for a in d["approval_rules"]),
            allowed_payees=tuple(d["allowed_payees"]),
            valid_from=dt(d["valid_from"]),
            valid_until=dt(d["valid_until"]),
            status=d.get("status", "active"),
        )
