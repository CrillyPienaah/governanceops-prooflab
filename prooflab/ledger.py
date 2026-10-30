"""Independent observer: the system of record for what actually happened.

The agent never writes here directly. Only the payment rail does, so ProofLab can
reconcile business outcomes against what the agent and its enforcement layer *claim*.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class LedgerEntry:
    seq: int
    tool: str
    amount: Decimal
    payee: str
    approval_id: str | None
    prev_hash: str
    entry_hash: str


class IndependentLedger:
    GENESIS = "0" * 64

    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []
        self.available = True  # set False to simulate observer outage

    def record(self, tool: str, amount: Decimal, payee: str, approval_id: str | None) -> LedgerEntry:
        prev = self._entries[-1].entry_hash if self._entries else self.GENESIS
        body = json.dumps({"seq": len(self._entries), "tool": tool, "amount": str(amount),
                           "payee": payee, "approval_id": approval_id, "prev": prev}, sort_keys=True)
        e = LedgerEntry(len(self._entries), tool, amount, payee, approval_id, prev,
                        hashlib.sha256(body.encode()).hexdigest())
        self._entries.append(e)
        return e

    def entries(self) -> list[LedgerEntry]:
        if not self.available:
            raise ConnectionError("independent ledger unavailable")
        return list(self._entries)

    def chain_intact(self) -> bool:
        prev = self.GENESIS
        for e in self._entries:
            body = json.dumps({"seq": e.seq, "tool": e.tool, "amount": str(e.amount), "payee": e.payee,
                               "approval_id": e.approval_id, "prev": prev}, sort_keys=True)
            if e.prev_hash != prev or hashlib.sha256(body.encode()).hexdigest() != e.entry_hash:
                return False
            prev = e.entry_hash
        return True
