"""Tests for the freshness / dir / json / command collectors and their clauses.

Run: python tests/test_collectors_extra.py

The staleness case is the interesting one. `file_exists` passes on a file written yesterday,
so an agent that "regenerated the report" and silently failed still looks successful. Only
freshness catches that, and it is the most common silent failure in anything that reruns.
"""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stepproof import (Ledger, VerificationError, command_output, dir_has_files,
                        file_newer_than, json_field, set_ledger, verified)
from stepproof.verify import _resolve

FAILS = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILS.append(f"{label}: got {got!r}, want {want!r}")
    print(f"{'ok  ' if ok else 'BAD '} {label}")


def tmpdir():
    return tempfile.mkdtemp()


def test_freshness():
    print("\n-- freshness: the stale-rerun failure --")
    d = tmpdir()
    fresh = os.path.join(d, "fresh.txt")
    stale = os.path.join(d, "stale.txt")
    for p in (fresh, stale):
        open(p, "w").write("DONE")
    os.utime(stale, (time.time() - 86400, time.time() - 86400))   # yesterday

    check("fresh file passes", file_newer_than(fresh, 300)[0], True)
    check("stale file FAILS", file_newer_than(stale, 300)[0], False)
    check("says STALE and the age", "STALE" in file_newer_than(stale, 300)[1], True)
    check("missing file fails", file_newer_than(os.path.join(d, "nope"), 300)[0], False)

    # the whole point: existence is not freshness
    from stepproof import file_exists
    check("file_exists would have PASSED the stale file", file_exists(stale)[0], True)


def test_dir():
    print("\n-- dir_has_files --")
    d = tmpdir()
    for n in ("a.png", "b.png", "notes.txt"):
        open(os.path.join(d, n), "w").write("x")

    check("count met", dir_has_files(d, 2, "*.png")[0], True)
    check("count not met", dir_has_files(d, 5, "*.png")[0], False)
    check("shortfall names what it found", "expected at least 5" in dir_has_files(d, 5, "*.png")[1], True)
    check("pattern respected", dir_has_files(d, 2, "*.txt")[0], False)
    check("missing dir fails", dir_has_files(os.path.join(d, "nope"), 1)[0], False)


def test_json():
    print("\n-- json_field --")
    d = tmpdir()
    p = os.path.join(d, "cfg.json")
    json.dump({"server": {"port": 8001, "tls": False}, "name": "demo"}, open(p, "w"))

    check("nested value matches", json_field(p, "server.port", 8001)[0], True)
    check("nested value differs", json_field(p, "server.port", 9999)[0], False)
    check("mismatch shows actual", "8001" in json_field(p, "server.port", 9999)[1], True)
    check("key presence only", json_field(p, "name")[0], True)
    check("missing key fails", json_field(p, "server.host")[0], False)
    check("missing key names where it stopped", "stopped at" in json_field(p, "server.host")[1], True)
    # False is a real value, not "absent" — the sentinel exists for exactly this
    check("False is a legitimate expected value", json_field(p, "server.tls", False)[0], True)

    bad = os.path.join(d, "bad.json")
    open(bad, "w").write("{not json")
    check("unreadable json fails cleanly", json_field(bad, "a")[0], False)


def test_command_output():
    print("\n-- command_output (real shell, unlike the demo's broken tool) --")
    ok, ev = command_output("echo hello", contains="hello")
    check("echo works with a real shell", ok, True)
    check("nonzero exit fails", command_output("exit 3")[0], False)
    check("missing text fails", command_output("echo hello", contains="goodbye")[0], False)

    # the contrast that makes the whole demo point: WITH a shell, the redirect works
    d = tmpdir()
    target = os.path.join(d, "redirected.txt")
    command_output(f'echo DONE > "{target}"')
    check("redirect actually wrote the file (shell=True)", os.path.exists(target), True)


def test_new_clauses():
    print("\n-- clause grammar for the new collectors --")
    d = tmpdir()
    p = os.path.join(d, "r.txt")
    open(p, "w").write("DONE")
    stale = os.path.join(d, "old.txt")
    open(stale, "w").write("DONE")
    os.utime(stale, (time.time() - 86400, time.time() - 86400))
    cfg = os.path.join(d, "c.json")
    json.dump({"server": {"port": 8001}}, open(cfg, "w"))
    for n in ("x.png", "y.png"):
        open(os.path.join(d, n), "w").write("x")

    for clause, args, want in [
        ("file {path} written within 300s", {"path": p}, True),
        ("file {path} written within 300s", {"path": stale}, False),
        ("dir {path} has 2 files matching *.png", {"path": d}, True),
        ("dir {path} has 9 files matching *.png", {"path": d}, False),
        ("json {path} has server.port = 8001", {"path": cfg}, True),
        ("json {path} has server.port = 9999", {"path": cfg}, False),
        ("json {path} has server.port", {"path": cfg}, True),
    ]:
        collector, _spec = _resolve(clause, args)
        check(f"{clause} -> {want}", collector()[0], want)


def test_stale_rerun_end_to_end():
    print("\n-- end to end: the rerun that quietly did nothing --")
    led = Ledger(os.path.join(tmpdir(), "l.jsonl"))
    set_ledger(led)
    d = tmpdir()
    report = os.path.join(d, "report.txt")
    open(report, "w").write("yesterday's report")
    os.utime(report, (time.time() - 86400, time.time() - 86400))

    @verified(proves="file {path} written within 60s")
    def regenerate_report(path):
        return "Report regenerated successfully."      # the write silently failed

    try:
        regenerate_report(report)
        check("stale rerun caught", False, True)
    except VerificationError as e:
        check("stale rerun caught", "STALE" in str(e), True)
        check("sealed as failed", list(led.read())[0].verified, False)


if __name__ == "__main__":
    test_freshness()
    test_dir()
    test_json()
    test_command_output()
    test_new_clauses()
    test_stale_rerun_end_to_end()

    print("\n" + "=" * 60)
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S):")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("ALL TESTS PASS")
