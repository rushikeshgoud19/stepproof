"""Shared adapter core.

Every framework adapter does the same three things — wrap a callable, seal what happened,
leave the original alone — and only differs in where the callable lives on that framework's
tool object. Writing that logic once per framework is how the same bug ends up fixed in one
place out of three, so it lives here and the adapters stay thin.
"""
from __future__ import annotations

from typing import Any, Callable

from ..verify import get_ledger, verified


def safe_args(args: tuple, kwargs: dict) -> dict:
    """Arguments for the audit trail, truncated. Sealed because 'what did it decide' is
    an audit question, and a tool call without its arguments answers half of it."""
    d = {f"arg{i}": str(a)[:120] for i, a in enumerate(args)}
    d.update({k: str(v)[:120] for k, v in kwargs.items()})
    return d


def seal_callable(fn: Callable, name: str = None, proves: str = None,
                  verifier: Callable = None, actor: str = "agent",
                  authorization: str = "", raises: bool = False) -> Callable:
    """Return a wrapped `fn` that seals every call.

    With `proves`/`verifier` the claimed effect is checked against real state. Without one,
    the call is RECORDED with `verified=None` — never True. An action nobody checked is not
    a passing action, and quietly promoting it would reproduce the exact failure this
    library exists to detect.
    """
    if proves or verifier:
        return verified(proves=proves, verifier=verifier, actor=actor,
                        authorization=authorization, raises=raises)(fn)

    label = name or getattr(fn, "__name__", "tool")

    def recorder(*args, **kwargs):
        try:
            result = fn(*args, **kwargs)
        except Exception as e:
            get_ledger().append(action=label, claimed=f"raised {type(e).__name__}: {e}",
                                verified=False, evidence=f"the call itself failed: {e}",
                                actor=actor, authorization=authorization,
                                args=safe_args(args, kwargs))
            raise
        get_ledger().append(action=label, claimed=str(result)[:300], verified=None,
                            evidence="not checked — no proves clause for this tool",
                            actor=actor, authorization=authorization,
                            args=safe_args(args, kwargs))
        return result

    recorder.__name__ = getattr(fn, "__name__", label)
    recorder.__doc__ = getattr(fn, "__doc__", None)
    return recorder


def seal_attr(tool: Any, attr: str, proves: str = None, verifier: Callable = None,
              actor: str = "agent", authorization: str = "", raises: bool = False,
              copy: bool = True) -> Any:
    """Seal the callable held at `tool.<attr>`, returning a copy of the tool by default.

    Copying matters: sealing must not mutate an object the caller may still be using
    elsewhere, and a test asserts exactly that.
    """
    fn = getattr(tool, attr, None)
    if not callable(fn):
        raise TypeError(
            f"{getattr(tool, 'name', tool)!r} has no callable .{attr} to wrap — pass the "
            f"underlying function to seal_callable() instead.")

    wrapped = seal_callable(fn, name=getattr(tool, "name", None), proves=proves,
                            verifier=verifier, actor=actor, authorization=authorization,
                            raises=raises)
    target = tool.copy() if (copy and hasattr(tool, "copy")) else tool
    setattr(target, attr, wrapped)
    return target
