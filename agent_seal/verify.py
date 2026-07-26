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
from typing import Any, Callable

from . import collectors
from .collectors import file_contains, file_exists
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


# ── The `proves=` clause grammar ────────────────────────────────────────────────
# A tiny English-ish DSL, kept deliberately small. Anything it cannot express is a sign you
# should pass verifier=<callable> instead — an unreadable clause is worse than a function.
#
# Each entry: (match predicate, parser -> a zero-arg collector call).

def _p_file_exists(spec: str):
    return lambda: collectors.file_exists(spec[len("file exists at "):].strip())


def _p_file_absent(spec: str):
    return lambda: collectors.file_absent(spec[len("no file at "):].strip())


def _p_file_contains(spec: str):
    target, needle = spec[len("file "):].split(" contains ", 1)
    return lambda: collectors.file_contains(target.strip(), needle.strip())


def _p_http(spec: str):
    rest = spec[len("http 200 from "):].strip()
    if " containing " in rest:
        url, needle = rest.split(" containing ", 1)
        return lambda: collectors.http_ok(url.strip(), contains=needle.strip())
    return lambda: collectors.http_ok(rest)


def _p_sqlite(spec: str):
    # "sqlite <db> has row in <table> where <clause>"
    rest = spec[len("sqlite "):]
    db, rest = rest.split(" has row in ", 1)
    if " where " in rest:
        table, where = rest.split(" where ", 1)
    else:
        table, where = rest, "1=1"
    return lambda: collectors.sqlite_row_exists(db.strip(), table.strip(), where.strip())


_CLAUSES = [
    (lambda s: s.startswith("file exists at "), _p_file_exists),
    (lambda s: s.startswith("no file at "), _p_file_absent),
    (lambda s: s.startswith("file ") and " contains " in s, _p_file_contains),
    (lambda s: s.startswith("http 200 from "), _p_http),
    (lambda s: s.startswith("sqlite ") and " has row in " in s, _p_sqlite),
]

_CLAUSE_HELP = """supported clauses:
    "file exists at {path}"
    "no file at {path}"
    "file {path} contains {text}"
    "http 200 from {url}"                     (optionally: ... containing {text})
    "sqlite {db} has row in {table} where {clause}"
or pass verifier=<callable> returning (ok, evidence)."""


def _resolve(proves: str, bound: dict) -> tuple[Callable[[], tuple[bool, str]], str]:
    """Turn a `proves=` string into a collector call.

    `{...}` fields are filled from the wrapped function's own arguments, so the contract is
    written once at the definition and stays correct for every call.
    """
    try:
        spec = proves.format(**bound)
    except KeyError as e:
        raise ValueError(
            f"proves clause {proves!r} references {e} which is not an argument of the "
            f"decorated function (it has: {sorted(bound)})") from None
    low = spec.lower()
    for matches, parse in _CLAUSES:
        if matches(low):
            return parse(spec), spec
    raise ValueError(f"unsupported proves clause: {proves!r}.\n{_CLAUSE_HELP}")


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
