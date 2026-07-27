"""Tests for stepproof. Run: python tests/test_stepproof.py

No pytest dependency — a verification library that is annoying to verify would be a poor
advertisement for itself.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stepproof import (Ledger, VerificationError, explain, is_narration, report,
                        set_ledger, verified)

FAILS = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILS.append(f"{label}: got {got!r}, want {want!r}")
    print(f"{'ok  ' if ok else 'BAD '} {label}")


def fresh_ledger():
    path = os.path.join(tempfile.mkdtemp(), "ledger.jsonl")
    led = Ledger(path)
    set_ledger(led)
    return led


# ── narration detector ──────────────────────────────────────────────────────────
def test_narration():
    print("\n-- narration detection --")
    # plans are not evidence
    check("plain intent", is_narration("I will use the file tool to check if it exists."), True)
    check("let me", is_narration("Let me verify that for you."), True)
    check("to verify this", is_narration("To verify this condition, I would read the file."), True)
    # refusals are not evidence (the false-NEGATIVE direction)
    check("refusal", is_narration("I'm sorry, I don't have access to files on a server."), True)
    check("as an ai", is_narration("As an AI, I cannot check the filesystem."), True)
    # real observations ARE evidence, including very short ones
    check("exit code", is_narration("exit 0"), False)
    check("short output", is_narration("WORKING"), False)
    check("not found", is_narration("no such file: /tmp/x"), False)
    check("timestamp", is_narration("2026-07-27 01:20:55"), False)
    # intent followed by an actual result is rescued
    check("intent then result", is_narration("I'll check now. output: DONE, exit 0"), False)
    check("refusal then result",
          is_narration("I'm sorry — but here it is anyway. exit 1, no such file"), False)
    # empty is never evidence
    check("empty", is_narration(""), True)
    check("whitespace", is_narration("   \n "), True)
    # the exact regression that motivated the strict result markers
    check("'exists' alone is NOT a result",
          is_narration("I will check if the file exists."), True)
    # explanations are for humans reading an audit trail
    assert "narration" in explain("I will check the file.")
    assert "refusal" in explain("I don't have access to files.")
    assert "accepted" in explain("exit 0")
    print("     explain(): narration/refusal/accepted all distinguishable")


# ── the core promise ────────────────────────────────────────────────────────────
def test_catches_the_lie():
    print("\n-- catches an action that never happened --")
    fresh_ledger()
    target = os.path.join(tempfile.mkdtemp(), "report.txt")

    @verified(proves="file exists at {path}")
    def write_report(path):
        return "Report written successfully."      # the claim, with no effect

    try:
        write_report(target)
        check("raises on unverifiable claim", False, True)
    except VerificationError as e:
        check("raises on unverifiable claim", True, True)
        check("error names the real state", "no such file" in str(e), True)


def test_passes_real_work():
    print("\n-- lets real work through --")
    fresh_ledger()
    target = os.path.join(tempfile.mkdtemp(), "real.txt")

    @verified(proves="file {path} contains DONE")
    def write_real(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("DONE")
        return "wrote it"

    check("returns normally", write_real(target), "wrote it")


def test_no_false_pass_on_wrong_content():
    print("\n-- content mismatch is still a failure --")
    fresh_ledger()
    target = os.path.join(tempfile.mkdtemp(), "wrong.txt")

    @verified(proves="file {path} contains DONE")
    def write_wrong(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("OOPS")
        return "wrote it"

    try:
        write_wrong(target)
        check("file exists but wrong content -> FAIL", False, True)
    except VerificationError as e:
        check("file exists but wrong content -> FAIL", "does not contain" in str(e), True)


def test_narration_evidence_rejected():
    print("\n-- a verifier that narrates cannot pass itself --")
    fresh_ledger()

    def lazy_verifier(**_):
        return True, "I will check whether that worked."   # claims ok, reports nothing

    @verified(verifier=lazy_verifier)
    def do_thing():
        return "done!"

    try:
        do_thing()
        check("narrating verifier rejected", False, True)
    except VerificationError as e:
        check("narrating verifier rejected", "non-evidence" in str(e), True)


# ── tamper evidence ─────────────────────────────────────────────────────────────
def test_chain_intact():
    print("\n-- hash chain --")
    led = fresh_ledger()
    for i in range(3):
        led.append(action=f"a{i}", claimed="ok", verified=True, evidence="exit 0")
    intact, detail = led.verify_chain()
    check("clean chain is intact", intact, True)


def test_detects_edit():
    print("\n-- tamper: a record is edited --")
    led = fresh_ledger()
    led.append(action="pay", claimed="sent $10", verified=False, evidence="no such transfer")
    led.append(action="log", claimed="ok", verified=True, evidence="exit 0")

    rows = [json.loads(l) for l in open(led.path, encoding="utf-8") if l.strip()]
    rows[0]["verified"] = True                       # cover up the failure
    rows[0]["evidence"] = "exit 0, all good"
    with open(led.path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    intact, detail = led.verify_chain()
    check("edited record detected", intact, False)
    check("detail names modification", "modified after sealing" in detail, True)


def test_detects_deletion():
    print("\n-- tamper: a record is deleted --")
    led = fresh_ledger()
    for i in range(3):
        led.append(action=f"a{i}", claimed="ok", verified=True, evidence="exit 0")
    rows = [l for l in open(led.path, encoding="utf-8") if l.strip()]
    del rows[1]                                       # remove the middle record
    with open(led.path, "w", encoding="utf-8") as f:
        f.writelines(rows)

    intact, detail = led.verify_chain()
    check("deleted record detected", intact, False)
    check("detail names removal", "removed or reordered" in detail, True)


def test_report_and_actor():
    print("\n-- audit report --")
    led = fresh_ledger()
    target = os.path.join(tempfile.mkdtemp(), "r.txt")

    @verified(proves="file exists at {path}", actor="nightly-agent",
              authorization="ops-policy-v2", raises=False)
    def sweep(path):
        return "all done"

    sweep(target)                                     # records instead of raising
    out = report(led)
    check("report counts the failure", "FAILED         : 1" in out, True)
    check("report carries the actor", "nightly-agent" in out, True)
    check("raises=False does not raise", True, True)
    seals = list(led.read())
    check("authorization sealed", seals[0].authorization, "ops-policy-v2")


if __name__ == "__main__":
    test_narration()
    test_catches_the_lie()
    test_passes_real_work()
    test_no_false_pass_on_wrong_content()
    test_narration_evidence_rejected()
    test_chain_intact()
    test_detects_edit()
    test_detects_deletion()
    test_report_and_actor()

    print("\n" + "=" * 60)
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S):")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("ALL TESTS PASS")
