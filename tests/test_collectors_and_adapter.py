"""Tests for the evidence collectors, the proves= clause grammar, and the LangChain adapter.

Run: python tests/test_collectors_and_adapter.py

The adapter tests use a fake tool object rather than importing LangChain — the core must
stay installable without it, and a test that silently skips is a test that rots.
"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_seal import (Ledger, VerificationError, file_absent, file_contains, file_exists,
                        output_contains, set_ledger, sqlite_row_exists, verified)
from agent_seal.verify import _resolve

FAILS = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILS.append(f"{label}: got {got!r}, want {want!r}")
    print(f"{'ok  ' if ok else 'BAD '} {label}")


def tmpfile(name="f.txt", body=None):
    p = os.path.join(tempfile.mkdtemp(), name)
    if body is not None:
        with open(p, "w", encoding="utf-8") as f:
            f.write(body)
    return p


def test_collectors():
    print("\n-- collectors --")
    present = tmpfile(body="DONE")
    missing = tmpfile()

    check("file_exists true", file_exists(present)[0], True)
    check("file_exists false", file_exists(missing)[0], False)
    check("file_exists says what it saw", "no such file" in file_exists(missing)[1], True)

    check("file_absent true", file_absent(missing)[0], True)
    check("file_absent false", file_absent(present)[0], False)

    check("file_contains true", file_contains(present, "DONE")[0], True)
    check("file_contains false", file_contains(present, "NOPE")[0], False)
    check("mismatch quotes real content", "DONE" in file_contains(present, "NOPE")[1], True)

    check("output_contains true", output_contains("exit 0, DONE", "DONE")[0], True)
    check("output_contains false", output_contains("exit 1", "DONE")[0], False)

    db = tmpfile("s.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE tasks (id INTEGER, desc TEXT, executed INT)")
    con.execute("INSERT INTO tasks VALUES (1, 'write report', 1)")
    con.commit(); con.close()

    check("sqlite row found", sqlite_row_exists(db, "tasks", "executed=1")[0], True)
    check("sqlite row absent", sqlite_row_exists(db, "tasks", "executed=0")[0], False)
    check("absent says count 0", "count 0" in sqlite_row_exists(db, "tasks", "executed=0")[1], True)
    check("missing db is a failure not a crash", sqlite_row_exists("/nope/x.db", "t")[0], False)
    check("bad table is a failure not a crash", sqlite_row_exists(db, "nosuch")[0], False)


def test_clause_grammar():
    print("\n-- proves= clause grammar --")
    p = tmpfile(body="DONE")
    db = tmpfile("g.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t (a INT)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit(); con.close()

    for clause, args, want in [
        ("file exists at {path}", {"path": p}, True),
        ("no file at {path}", {"path": p}, False),
        ("file {path} contains {word}", {"path": p, "word": "DONE"}, True),
        ("file {path} contains {word}", {"path": p, "word": "MISSING"}, False),
        ("sqlite {db} has row in t where a=1", {"db": db}, True),
        ("sqlite {db} has row in t where a=99", {"db": db}, False),
    ]:
        collector, spec = _resolve(clause, args)
        check(f"{clause} -> {want}", collector()[0], want)

    # a clause naming an argument the function doesn't have must fail LOUDLY at call time,
    # not silently verify nothing
    try:
        _resolve("file exists at {nope}", {"path": p})
        check("unknown field raises", False, True)
    except ValueError as e:
        check("unknown field raises", "not an argument" in str(e), True)

    try:
        _resolve("the vibes are good", {})
        check("unsupported clause raises with help", False, True)
    except ValueError as e:
        check("unsupported clause raises with help", "supported clauses" in str(e), True)


# ── adapter ─────────────────────────────────────────────────────────────────────
class FakeTool:
    """Stands in for a LangChain BaseTool: has .name, .func, and .copy()."""
    def __init__(self, name, func):
        self.name, self.func = name, func

    def copy(self):
        return FakeTool(self.name, self.func)

    def invoke(self, kwargs):
        return self.func(**kwargs)


def test_adapter_records_without_claiming_verified():
    print("\n-- adapter: record mode --")
    led = Ledger(tmpfile("l1.jsonl")); set_ledger(led)
    from agent_seal.adapters.langchain import seal_tools

    def do_nothing(path: str) -> str:
        return "exit 0. all good"

    tools = seal_tools([FakeTool("run_shell", do_nothing)])
    tools[0].invoke({"path": "/tmp/whatever"})

    seals = list(led.read())
    check("call was sealed", len(seals), 1)
    check("NOT marked verified", seals[0].verified, None)
    check("evidence says unchecked", "not checked" in seals[0].evidence, True)
    check("counted as never-checked", len(led.unverified()), 1)
    check("not counted as a pass", len([s for s in seals if s.verified is True]), 0)


def test_adapter_verifies_named_tool():
    print("\n-- adapter: verify mode --")
    led = Ledger(tmpfile("l2.jsonl")); set_ledger(led)
    from agent_seal.adapters.langchain import seal_tools

    target = tmpfile("out.txt")

    def fake_write(path: str) -> str:
        return "exit 0. stdout: 'DONE > out.txt'"      # the real bug: writes nothing

    tools = seal_tools([FakeTool("run_shell", fake_write)],
                       proves={"run_shell": "file exists at {path}"})
    tools[0].invoke({"path": target})

    seals = list(led.read())
    check("sealed", len(seals), 1)
    check("caught the fake success", seals[0].verified, False)
    check("evidence names reality", "no such file" in seals[0].evidence, True)
    check("appears in failures()", len(led.failures()), 1)


def test_adapter_seals_exceptions():
    print("\n-- adapter: a raising tool is still sealed --")
    led = Ledger(tmpfile("l3.jsonl")); set_ledger(led)
    from agent_seal.adapters.langchain import seal_tools

    def boom(x: str) -> str:
        raise RuntimeError("network down")

    tools = seal_tools([FakeTool("call_api", boom)])
    try:
        tools[0].invoke({"x": "1"})
    except RuntimeError:
        pass
    seals = list(led.read())
    check("failure sealed", len(seals), 1)
    check("marked failed", seals[0].verified, False)
    check("evidence carries the error", "network down" in seals[0].evidence, True)


def test_adapter_leaves_original_untouched():
    print("\n-- adapter: original tool not mutated --")
    led = Ledger(tmpfile("l4.jsonl")); set_ledger(led)
    from agent_seal.adapters.langchain import seal_tools

    def f(x: str) -> str:
        return "ok"

    original = FakeTool("t", f)
    sealed = seal_tools([original])[0]
    original.invoke({"x": "1"})
    check("original does not seal", len(list(led.read())), 0)
    sealed.invoke({"x": "1"})
    check("sealed copy does seal", len(list(led.read())), 1)


if __name__ == "__main__":
    test_collectors()
    test_clause_grammar()
    test_adapter_records_without_claiming_verified()
    test_adapter_verifies_named_tool()
    test_adapter_seals_exceptions()
    test_adapter_leaves_original_untouched()

    print("\n" + "=" * 60)
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S):")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("ALL TESTS PASS")
