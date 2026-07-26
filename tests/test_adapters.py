"""Adapter tests for all three frameworks.

Run: python tests/test_adapters.py

None of the frameworks are installed to run these, on purpose. The adapters only need a
tool object with a name and a callable attribute, so stand-ins model exactly that contract
— and the core stays installable with zero dependencies, which is the whole pitch. Tests
that silently skip when a framework is missing are tests that rot unnoticed.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_seal import Ledger, set_ledger
from agent_seal.adapters import crewai as crew_ad
from agent_seal.adapters import langchain as lc_ad
from agent_seal.adapters import openai_agents as oai_ad

FAILS = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILS.append(f"{label}: got {got!r}, want {want!r}")
    print(f"{'ok  ' if ok else 'BAD '} {label}")


def fresh():
    led = Ledger(os.path.join(tempfile.mkdtemp(), "l.jsonl"))
    set_ledger(led)
    return led


def tmppath(name="out.txt"):
    return os.path.join(tempfile.mkdtemp(), name)


# ── stand-ins modelling each framework's tool shape ──────────────────────────────
class LangChainTool:
    """StructuredTool: callable on .func, has .copy()."""
    def __init__(self, name, func):
        self.name, self.func = name, func

    def copy(self):
        return LangChainTool(self.name, self.func)

    def invoke(self, kw):
        return self.func(**kw)


class OpenAIAgentsTool:
    """function_tool: callable on .on_invoke_tool, no .copy()."""
    def __init__(self, name, fn):
        self.name, self.on_invoke_tool = name, fn

    def invoke(self, kw):
        return self.on_invoke_tool(**kw)


class CrewAITool:
    """BaseTool subclass: callable on ._run, name has spaces."""
    def __init__(self, name, fn):
        self.name, self._run = name, fn

    def invoke(self, kw):
        return self._run(**kw)


def fake_write(path: str) -> str:
    """The real bug: reports exit 0, writes nothing."""
    return "exit 0. stdout: 'DONE > out.txt'"


def real_write(path: str) -> str:
    with open(path, "w", encoding="utf-8") as f:
        f.write("DONE")
    return "exit 0"


CASES = [
    ("langchain", lc_ad, LangChainTool, "run_shell"),
    ("openai_agents", oai_ad, OpenAIAgentsTool, "run_shell"),
    ("crewai", crew_ad, CrewAITool, "Write File"),
]


def test_record_mode():
    print("\n-- record mode: sealed but NOT claimed verified --")
    for label, adapter, ToolCls, name in CASES:
        led = fresh()
        tools = adapter.seal_tools([ToolCls(name, fake_write)])
        tools[0].invoke({"path": tmppath()})
        seals = list(led.read())
        check(f"{label}: sealed", len(seals), 1)
        check(f"{label}: verified is None", seals[0].verified, None)
        check(f"{label}: counted never-checked", len(led.unverified()), 1)
        check(f"{label}: tool name kept", seals[0].action, name)


def test_verify_catches_fake_success():
    print("\n-- verify mode: catches the fake success --")
    for label, adapter, ToolCls, name in CASES:
        led = fresh()
        target = tmppath()
        tools = adapter.seal_tools([ToolCls(name, fake_write)],
                                   proves={name: "file exists at {path}"})
        tools[0].invoke({"path": target})
        seals = list(led.read())
        check(f"{label}: caught", seals[0].verified, False)
        check(f"{label}: evidence is real state", "no such file" in seals[0].evidence, True)


def test_verify_passes_real_work():
    print("\n-- verify mode: real work passes --")
    for label, adapter, ToolCls, name in CASES:
        led = fresh()
        target = tmppath()
        tools = adapter.seal_tools([ToolCls(name, real_write)],
                                   proves={name: "file {path} contains DONE"})
        tools[0].invoke({"path": target})
        check(f"{label}: verified true", list(led.read())[0].verified, True)


def test_actor_recorded():
    print("\n-- actor/authorization survive the adapter --")
    for label, adapter, ToolCls, name in CASES:
        led = fresh()
        tools = adapter.seal_tools([ToolCls(name, fake_write)], actor="crew-agent-2",
                                   authorization="policy-v3")
        tools[0].invoke({"path": tmppath()})
        seal = list(led.read())[0]
        check(f"{label}: actor sealed", seal.actor, "crew-agent-2")
        check(f"{label}: authorization sealed", seal.authorization, "policy-v3")


def test_exception_sealed_and_reraised():
    print("\n-- a raising tool is sealed, then re-raised --")
    def boom(path: str) -> str:
        raise RuntimeError("network down")

    for label, adapter, ToolCls, name in CASES:
        led = fresh()
        tools = adapter.seal_tools([ToolCls(name, boom)])
        raised = False
        try:
            tools[0].invoke({"path": "x"})
        except RuntimeError:
            raised = True
        check(f"{label}: re-raised", raised, True)
        seal = list(led.read())[0]
        check(f"{label}: sealed as failed", seal.verified, False)
        check(f"{label}: error in evidence", "network down" in seal.evidence, True)


def test_args_are_sealed():
    print("\n-- arguments land in the trail --")
    led = fresh()
    tools = lc_ad.seal_tools([LangChainTool("run_shell", fake_write)])
    tools[0].invoke({"path": "/tmp/audited.txt"})
    check("args recorded", "/tmp/audited.txt" in str(list(led.read())[0].args), True)


def test_unwrappable_tool_is_loud():
    print("\n-- a tool with no callable fails loudly, never silently --")
    class Opaque:
        name = "mystery"

    for label, adapter, _, _n in CASES:
        try:
            adapter.seal_tools([Opaque()])
            check(f"{label}: raises on unwrappable", False, True)
        except TypeError as e:
            check(f"{label}: raises on unwrappable", "no callable" in str(e).lower(), True)


def test_original_not_mutated_langchain():
    print("\n-- sealing does not mutate the original (where copy() exists) --")
    led = fresh()
    original = LangChainTool("run_shell", fake_write)
    sealed = lc_ad.seal_tools([original])[0]
    original.invoke({"path": tmppath()})
    check("original stays unsealed", len(list(led.read())), 0)
    sealed.invoke({"path": tmppath()})
    check("sealed copy seals", len(list(led.read())), 1)


if __name__ == "__main__":
    test_record_mode()
    test_verify_catches_fake_success()
    test_verify_passes_real_work()
    test_actor_recorded()
    test_exception_sealed_and_reraised()
    test_args_are_sealed()
    test_unwrappable_tool_is_loud()
    test_original_not_mutated_langchain()

    print("\n" + "=" * 60)
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S):")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("ALL TESTS PASS")
