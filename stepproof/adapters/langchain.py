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

from ._common import seal_attr

# LangChain keeps a StructuredTool's callable on `.func`.
_ATTR = "func"


def seal_tool(tool: Any, proves: str = None, verifier: Callable = None,
              actor: str = "agent", authorization: str = "", raises: bool = False):
    """Seal ONE LangChain tool. Returns a copy; the original is untouched.

    `raises` defaults to False here (unlike the bare decorator) because raising inside an
    agent's tool loop turns a detectable failure into a crash — inside a framework you
    usually want the run to finish and the report to tell you what was fake.
    """
    return seal_attr(tool, _ATTR, proves=proves, verifier=verifier, actor=actor,
                     authorization=authorization, raises=raises)


def seal_tools(tools: Iterable[Any], proves: dict[str, str] = None,
               actor: str = "agent", authorization: str = "",
               raises: bool = False) -> list:
    """Seal a whole toolbelt. `proves` maps tool name -> clause; unnamed tools are recorded.

        tools = seal_tools(tools, proves={"run_shell": "file {path} contains DONE"})

    The clause is filled from the TOOL's arguments, so it can only reference parameters that
    tool actually takes.
    """
    proves = proves or {}
    return [seal_tool(t, proves=proves.get(getattr(t, "name", None)), actor=actor,
                      authorization=authorization, raises=raises) for t in tools]
