"""Hash-chained, append-only seal ledger.

An audit trail nobody can quietly edit is the difference between a log and evidence.
Every seal carries the hash of the one before it, so removing or altering a record breaks
the chain from that point forward and `verify_chain()` reports exactly where.

Deliberately dependency-free and backed by plain JSONL: an audit artifact you cannot read
without the tool that wrote it is worth very little, and a reviewer should be able to open
this file in any editor.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Iterator

GENESIS = "0" * 64


@dataclass(frozen=True)
class Seal:
    """One immutable record: what was attempted, what was claimed, what was observed."""
    action: str
    claimed: str                      # what the agent said happened
    verified: bool | None             # True / False / None = not checked
    evidence: str                     # the observation the verdict rests on
    actor: str = "unknown"            # WHO authorized this — an audit requirement
    authorization: str = ""           # under what grant/policy
    args: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    prev_hash: str = GENESIS
    hash: str = ""

    def digest(self) -> str:
        """Hash over every field except `hash` itself, with stable key order."""
        body = {k: v for k, v in asdict(self).items() if k != "hash"}
        return hashlib.sha256(
            json.dumps(body, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()


class Ledger:
    """Append-only JSONL ledger. Thread-safe; one process owns one file."""

    def __init__(self, path: str = ".agent_seal/ledger.jsonl"):
        self.path = path
        self._lock = threading.Lock()
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)

    def _last_hash(self) -> str:
        last = GENESIS
        for seal in self.read():
            last = seal.hash
        return last

    def append(self, **kwargs: Any) -> Seal:
        with self._lock:
            seal = Seal(prev_hash=self._last_hash(), **kwargs)
            seal = Seal(**{**asdict(seal), "hash": seal.digest()})
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(seal), default=str) + "\n")
            return seal

    def read(self) -> Iterator[Seal]:
        if not os.path.exists(self.path):
            return
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield Seal(**json.loads(line))

    def verify_chain(self) -> tuple[bool, str]:
        """Recompute the chain. Returns (intact, detail).

        Catches both tampering (a field was edited -> its own hash no longer matches) and
        deletion (a record was removed -> the next record's prev_hash points at nothing).
        """
        prev = GENESIS
        for i, seal in enumerate(self.read()):
            if seal.prev_hash != prev:
                return False, (f"chain broken at record {i} ({seal.action!r}): "
                               f"prev_hash {seal.prev_hash[:12]}… does not match the previous "
                               f"record's hash {prev[:12]}… — a record was removed or reordered")
            if seal.digest() != seal.hash:
                return False, (f"record {i} ({seal.action!r}) was modified after sealing: "
                               f"contents hash to {seal.digest()[:12]}… but it carries "
                               f"{seal.hash[:12]}…")
            prev = seal.hash
        return True, f"chain intact ({sum(1 for _ in self.read())} records)"

    def failures(self) -> list[Seal]:
        """Every action whose claimed effect could not be confirmed — the audit report."""
        return [s for s in self.read() if s.verified is False]

    def unverified(self) -> list[Seal]:
        """Actions nobody checked. Not failures, but not evidence of success either."""
        return [s for s in self.read() if s.verified is None]
