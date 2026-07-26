"""CrewAI adapter.

    from agent_seal.adapters.crewai import seal_tools
    agent.tools = seal_tools(agent.tools, proves={"Write File": "file exists at {path}"})

CrewAI tools carry their callable on `.func` (`@tool`-decorated functions) or expose a
`_run` method (`BaseTool` subclasses), so both are handled.

A CrewAI-specific note worth stating: crews delegate between agents, so the same underlying
tool can be invoked by several of them. Pass `actor=` when sealing per agent — "who
authorized this" is an audit question, and in a multi-agent crew it is the one that gets
hardest to answer after the fact.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

from ._common import seal_attr

_ATTRS = ("func", "_run", "run")


def _find_attr(tool: Any) -> str:
    for attr in _ATTRS:
        if callable(getattr(tool, attr, None)):
            return attr
    raise TypeError(
        f"{getattr(tool, 'name', tool)!r} exposes no callable in {_ATTRS}. Seal the "
        f"underlying function directly with @verified instead.")


def seal_tool(tool: Any, proves: str = None, verifier: Callable = None,
              actor: str = "agent", authorization: str = "", raises: bool = False):
    """Seal ONE CrewAI tool.

    BaseTool subclasses are pydantic models without a plain `.copy()` that behaves like a
    shallow clone, so sealing may happen in place; the return value is always the object to
    use.
    """
    return seal_attr(tool, _find_attr(tool), proves=proves, verifier=verifier, actor=actor,
                     authorization=authorization, raises=raises)


def seal_tools(tools: Iterable[Any], proves: dict[str, str] = None,
               actor: str = "agent", authorization: str = "",
               raises: bool = False) -> list:
    """Seal a whole toolbelt. `proves` maps tool name -> clause.

    CrewAI tool names contain spaces ("Write File"), so the keys are those display names.
    """
    proves = proves or {}
    return [seal_tool(t, proves=proves.get(getattr(t, "name", None)), actor=actor,
                      authorization=authorization, raises=raises) for t in tools]
