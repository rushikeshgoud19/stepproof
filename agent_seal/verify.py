"""verify-after-act: check the world, not the wording.

The failure this library exists for is not an agent lying. It is an agent honestly relaying
a tool that honestly returned success while producing no effect — nobody in the chain is
wrong, and output-level evaluation cannot see the gap by construction.

So the only question worth asking after an action is: **is the claimed effect present in
real state?** `@verified` asks it automatically and seals the answer.
"""
from __future__ import annotations

import functools
import inspect
import os
from typing import Any, Callable

from .ledger import Ledger, Seal
from .narration import explain, is_narration

_default_ledger: Ledger | None = None


def get_ledger() -> Ledger:
    global _default_ledger
    if _default_ledger is None:
        _default_ledger = Ledger()
    return _default_ledger


def set_ledger(ledger: Ledger) -> None:
    """Point the decorator at a specific ledger (tests, or one ledger per agent run)."""
    global _default_ledger
    _default_ledger = ledger


class VerificationError(AssertionError):
    """Raised when an action's claimed effect cannot be confirmed against real state."""


# ── Evidence collectors ─────────────────────────────────────────────────────────
# A collector answers one question about the world and returns (ok, evidence). Evidence is
# a STRING because it goes in the audit trail for a human to read later.

def file_exists(path: str) -> tuple[bool, str]:
    if not os.path.exists(path):
        return False, f"no such file: {path}"
    return True, f"file exists: {path} ({os.path.getsize(path)} bytes)"


def file_contains(path: str, needle: str) -> tuple[bool, str]:
    if not os.path.exists(path):
        return False, f"no such file: {path}"
    body = open(path, encoding="utf-8", errors="replace").read()
    if needle not in body:
        return False, f"file exists but does not contain {needle!r}; output: {body[:120]!r}"
    return True, f"file contains {needle!r} ({os.path.getsize(path)} bytes)"


def _resolve(proves: str, bound: dict) -> tuple[Callable[[], tuple[bool, str]], str]:
    """Turn a `proves=` string into a collector call.

    Supported today:
        "file exists at {path}"
        "file {path} contains {word}"
    `{...}` fields are filled from the wrapped function's own arguments, so the contract is
    written once at the definition and stays correct for every call.
    """
    spec = proves.format(**bound)
    low = spec.lower()
    if low.startswith("file exists at "):
        target = spec[len("file exists at "):].strip()
        return (lambda: file_exists(target)), spec
    if low.startswith("file ") and " contains " in low:
        rest = spec[len("file "):]
        target, needle = rest.split(" contains ", 1)
        return (lambda: file_contains(target.strip(), needle.strip())), spec
    raise ValueError(
        f"unsupported proves clause: {proves!r}. Use 'file exists at {{path}}' or "
        f"'file {{path}} contains {{word}}', or pass verifier=<callable> instead.")


def verified(proves: str = None, verifier: Callable[..., tuple] = None,
             actor: str = "agent", authorization: str = "", raises: bool = True):
    """Seal an action and confirm its claimed effect actually happened.

    @verified(proves="file exists at {path}")
    def write_report(path): ...

    The wrapped function may return normally — that is the *claim*. The collector then looks
    at real state — that is the *evidence*. Both go in the ledger, and by default a mismatch
    raises rather than returning quietly, because a verification layer that only logs is one
    more thing nobody reads.

    Pass raises=False to record and continue (useful when sweeping an existing agent to find
    out how much of what it reports is real).
    """
    if not proves and not verifier:
        raise ValueError("verified() needs either proves= or verifier=")

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            sig = inspect.signature(fn)
            bound = sig.bind_partial(*args, **kwargs)
            bound.apply_defaults()
            fields = dict(bound.arguments)

            try:
                result = fn(*args, **kwargs)
                claimed = str(result) if result is not None else "completed"
            except Exception as e:
                get_ledger().append(action=fn.__name__, claimed=f"raised {type(e).__name__}: {e}",
                                    verified=False, evidence=f"the call itself failed: {e}",
                                    actor=actor, authorization=authorization,
                                    args={k: str(v)[:120] for k, v in fields.items()})
                raise

            if verifier:
                ok, evidence = verifier(**fields) if _accepts_kwargs(verifier, fields) else verifier()
                spec = getattr(verifier, "__name__", "custom verifier")
            else:
                collector, spec = _resolve(proves, fields)
                ok, evidence = collector()

            # A verifier may itself return prose rather than an observation (common when the
            # collector is an LLM). Narration is not evidence, so refuse to count it.
            if ok and is_narration(evidence):
                ok, evidence = False, f"rejected non-evidence — {explain(evidence)}"

            seal = get_ledger().append(
                action=fn.__name__, claimed=claimed[:300], verified=bool(ok),
                evidence=str(evidence)[:300], actor=actor, authorization=authorization,
                args={k: str(v)[:120] for k, v in fields.items()})

            if not ok and raises:
                raise VerificationError(
                    f"{fn.__name__} reported {claimed[:80]!r} but {spec!r} is not true: "
                    f"{evidence}")
            return result
        return wrapper
    return decorator


def _accepts_kwargs(fn: Callable, fields: dict) -> bool:
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return True
    return bool(params) and all(k in params for k in fields)


def report(ledger: Ledger = None) -> str:
    """Human-readable audit summary — the artifact an auditor or a reviewer actually reads."""
    led = ledger or get_ledger()
    seals: list[Seal] = list(led.read())
    intact, detail = led.verify_chain()
    fails = [s for s in seals if s.verified is False]
    unchecked = [s for s in seals if s.verified is None]

    lines = ["AGENT-SEAL AUDIT REPORT",
             "=" * 60,
             f"actions sealed : {len(seals)}",
             f"verified true  : {sum(1 for s in seals if s.verified is True)}",
             f"FAILED         : {len(fails)}",
             f"never checked  : {len(unchecked)}",
             f"chain          : {'INTACT' if intact else 'BROKEN'} — {detail}"]
    if fails:
        lines += ["", "actions that did NOT happen as claimed:"]
        for s in fails:
            lines.append(f"  - {s.action}: claimed {s.claimed[:60]!r}")
            lines.append(f"      reality: {s.evidence[:90]}")
            lines.append(f"      actor: {s.actor}")
    return "\n".join(lines)
