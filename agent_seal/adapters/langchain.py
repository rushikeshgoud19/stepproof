"""LangChain adapter — seal an agent's tools without rewriting them.

Two modes, and the difference matters:

    seal_tools(tools)                      # RECORD: every call sealed, verified=None
    seal_tools(tools, proves={...})        # VERIFY: named tools checked against real state

`seal_tools(tools)` alone deliberately does NOT mark anything verified. It builds the trail
— what was called, with which arguments, what came back — and leaves the verdict blank.
Calling an unchecked action "verified" because nothing threw would be the exact mistake this
library is about, so the ledger reports those separately as `never checked`.

That recording mode is the honest way in: point it at an existing agent, run your normal
workload, then read `report()` to see how much of what it does is actually confirmed. Add
`proves=` clauses for the actions that matter.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

from ..verify import get_ledger, verified


def seal_tool(tool: Any, proves: str = None, verifier: Callable = None,
              actor: str = "agent", authorization: str = "", raises: bool = False):
    """Wrap ONE LangChain tool so its calls are sealed.

    Returns a new tool; the original is untouched. `raises` defaults to False here (unlike
    the bare decorator) because raising inside an agent's tool loop turns a detectable
    failure into a crash — inside a framework you usually want the run to finish and the
    report to tell you what was fake.
    """
    original = tool.func if hasattr(tool, "func") and tool.func else None
    if original is None:
        raise TypeError(f"{getattr(tool, 'name', tool)!r} has no .func to wrap — pass a "
                        f"@tool-decorated function, or seal the underlying callable directly.")

    if proves or verifier:
        wrapped = verified(proves=proves, verifier=verifier, actor=actor,
                           authorization=authorization, raises=raises)(original)
    else:
        def wrapped(*args, __orig=original, __name=tool.name, **kwargs):
            try:
                result = __orig(*args, **kwargs)
            except Exception as e:
                get_ledger().append(action=__name, claimed=f"raised {type(e).__name__}: {e}",
                                    verified=False, evidence=f"the call itself failed: {e}",
                                    actor=actor, authorization=authorization,
                                    args=_safe_args(args, kwargs))
                raise
            # verified=None on purpose: recorded, NOT confirmed. See the module docstring.
            get_ledger().append(action=__name, claimed=str(result)[:300], verified=None,
                                evidence="not checked — no proves clause for this tool",
                                actor=actor, authorization=authorization,
                                args=_safe_args(args, kwargs))
            return result
        wrapped.__name__ = original.__name__
        wrapped.__doc__ = original.__doc__

    new = tool.copy() if hasattr(tool, "copy") else tool
    new.func = wrapped
    return new


def seal_tools(tools: Iterable[Any], proves: dict[str, str] = None,
               actor: str = "agent", authorization: str = "",
               raises: bool = False) -> list:
    """Seal a whole toolbelt. `proves` maps tool name -> clause; unnamed tools are recorded.

        tools = seal_tools(tools, proves={"run_shell": "file {path} contains DONE"})

    Note the clause is filled from the TOOL's arguments, so it can only reference parameters
    that tool actually takes.
    """
    proves = proves or {}
    out = []
    for t in tools:
        name = getattr(t, "name", None)
        out.append(seal_tool(t, proves=proves.get(name), actor=actor,
                             authorization=authorization, raises=raises))
    return out


def _safe_args(args: tuple, kwargs: dict) -> dict:
    d = {f"arg{i}": str(a)[:120] for i, a in enumerate(args)}
    d.update({k: str(v)[:120] for k, v in kwargs.items()})
    return d
