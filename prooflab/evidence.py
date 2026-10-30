"""Verdicts and portable evidence bundles (HMAC-SHA256 signed manifest)."""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field, asdict
from enum import Enum


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass
class Finding:
    test_id: str
    control: str
    verdict: Verdict
    expected: str
    observed: str
    agent_reported: dict = field(default_factory=dict)
    ledger_observed: dict = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)


@dataclass
class EvidenceBundle:
    contract_id: str
    approved_policy_hash: str
    ledger_head: str
    findings: list[Finding]
    signature: str = ""

    def manifest(self) -> bytes:
        d = asdict(self)
        d.pop("signature")
        return json.dumps(d, sort_keys=True, default=str).encode()

    def sign(self, key: bytes) -> "EvidenceBundle":
        self.signature = hmac.new(key, self.manifest(), hashlib.sha256).hexdigest()
        return self

    def verify(self, key: bytes) -> bool:
        expected = hmac.new(key, self.manifest(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, self.signature)
