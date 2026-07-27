"""OpenAI Agents SDK adapter.

Same two modes as the other adapters — record everything, verify what you name:

    from stepproof.adapters.openai_agents import seal_tools
    tools = seal_tools(tools, proves={"write_report": "file exists at {path}"})

The SDK's `function_tool` keeps the underlying callable on `.on_invoke_tool` for hosted
tools and `.func` for plain function tools depending on version, so both are tried. If
neither is present the error says so plainly rather than silently sealing nothing — an
adapter that no-ops is worse than no adapter, because it produces a clean report about
nothing.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

from ._common import seal_attr

# Checked in order; the first callable attribute found is the one wrapped.
_ATTRS = ("func", "on_invoke_tool", "_fn", "callable")


def _find_attr(tool: Any) -> str:
    for attr in _ATTRS:
        if callable(getattr(tool, attr, None)):
            return attr
    raise TypeError(
        f"{getattr(tool, 'name', tool)!r} exposes no callable in {_ATTRS}. If your SDK "
        f"version stores it elsewhere, seal the function directly:\n"
        f"    from stepproof import verified\n"
        f"    @verified(proves=...)\n"
        f"    def my_tool(...): ...")


def seal_tool(tool: Any, proves: str = None, verifier: Callable = None,
              actor: str = "agent", authorization: str = "", raises: bool = False):
    """Seal ONE OpenAI Agents SDK tool. Returns a copy where the SDK supports it."""
    return seal_attr(tool, _find_attr(tool), proves=proves, verifier=verifier, actor=actor,
                     authorization=authorization, raises=raises)


def seal_tools(tools: Iterable[Any], proves: dict[str, str] = None,
               actor: str = "agent", authorization: str = "",
               raises: bool = False) -> list:
    """Seal a whole toolbelt. `proves` maps tool name -> clause."""
    proves = proves or {}
    return [seal_tool(t, proves=proves.get(getattr(t, "name", None)), actor=actor,
                      authorization=authorization, raises=raises) for t in tools]
