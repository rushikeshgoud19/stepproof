"""Tests for stepproof.seams. Run: python tests/test_seams.py

No pytest dependency — same reason as the rest of the suite.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stepproof.seams import Seams, SeamContract, SeamMissing

FAILS = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILS.append(f"{label}: got {got!r}, want {want!r}")
    print(f"{'ok  ' if ok else 'BAD '} {label}")


def raises(label, exc, fn):
    try:
        fn()
    except exc:
        print(f"ok   {label}")
        return
    except Exception as e:                                   # wrong type is still a failure
        FAILS.append(f"{label}: raised {type(e).__name__}, want {exc.__name__}")
        print(f"BAD  {label}")
        return
    FAILS.append(f"{label}: did not raise {exc.__name__}")
    print(f"BAD  {label}")


class Cron:
    """Stands in for the real CronManager — note it has no peek_due_soon."""

    def run_pending(self):
        return []


class GoodCron(Cron):
    def peek_due_soon(self):
        return ["backup at 03:00"]


# -- the bug this module exists for ----------------------------------------------
# `getattr(cron, "peek_due_soon", lambda: [])()` returns [] forever and looks like a
# working feature with nothing to report. Every assertion below is that shape, refused.

def test_undeclared_seam_is_loud():
    s = Seams()
    raises("require of an undeclared seam raises",
           SeamMissing, lambda: s.require("cron", consumer="subconscious"))


def test_declared_but_unprovided_is_loud():
    s = Seams()
    s.declare("cron", "Scheduled task source", methods=("peek_due_soon",), declared_by="t")
    raises("require with no provider raises",
           SeamMissing, lambda: s.require("cron", consumer="subconscious"))
    check("unwired lists it", s.unwired(), ["cron"])


def test_provider_missing_the_interface_fails_at_registration():
    s = Seams()
    s.declare("cron", "Scheduled task source", methods=("peek_due_soon",), declared_by="t")
    # The real defect: Cron looks plausible and is missing exactly one method.
    raises("provider missing a declared method raises at registration",
           SeamContract, lambda: s.provide("cron", Cron(), source="t"))
    check("a rejected provider does not count as wired", s.has("cron"), False)


def test_provider_with_the_interface_resolves():
    s = Seams()
    s.declare("cron", "Scheduled task source", methods=("peek_due_soon",), declared_by="t")
    s.provide("cron", GoodCron(), source="t.good")
    check("require returns the provider",
          s.require("cron", consumer="subconscious").peek_due_soon(),
          ["backup at 03:00"])
    check("nothing unwired", s.unwired(), [])


def test_provider_for_undeclared_seam_is_refused():
    s = Seams()
    raises("a provider with no definition is half a seam",
           SeamMissing, lambda: s.provide("cron", GoodCron(), source="t"))


def test_redeclaring_a_different_interface_is_refused():
    s = Seams()
    s.declare("cron", "v1", methods=("peek_due_soon",), declared_by="a")
    check("same interface re-declares cleanly",
          s.declare("cron", "v1", methods=("peek_due_soon",), declared_by="a").name, "cron")
    raises("two modules disagreeing about the interface raises",
           SeamContract,
           lambda: s.declare("cron", "v2", methods=("due_now",), declared_by="b"))


def test_optional_degrades_on_purpose():
    s = Seams()
    s.declare("search", "Paid backend", methods=("query",), declared_by="t")
    check("optional returns the default when absent",
          s.optional("search", default="none", consumer="t"), "none")


def test_graph_is_evidence():
    s = Seams()
    s.declare("cron", "Scheduled task source", methods=("peek_due_soon",), declared_by="t")
    s.declare("search", "Paid backend", methods=("query",), declared_by="t")
    s.provide("cron", GoodCron(), source="t.good")
    try:
        s.require("search", consumer="planner")
    except SeamMissing:
        pass
    rows = {r["seam"]: r for r in s.graph()}
    check("wired seam reports its provider", rows["cron"]["provider"], "t.good")
    check("wired flag is true", rows["cron"]["wired"], True)
    check("unwired flag is false", rows["search"]["wired"], False)
    check("a failed require is still recorded as a consumer",
          rows["search"]["consumers"], ["planner"])
    report = s.report()
    check("report marks the unwired seam", "!! search" in report, True)
    check("report marks the wired seam", "OK cron" in report, True)


def test_registries_are_independent():
    a, b = Seams(), Seams()
    a.declare("cron", methods=(), declared_by="a")
    check("a declaration does not leak between registries", b.unwired(), [])


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S)")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("all seam checks passed")
