"""Evidence collectors — the things that actually go and look.

A collector answers ONE question about the world and returns `(ok, evidence)`. Evidence is
a string because it lands in an audit trail a human reads later; "False" tells a reviewer
nothing, "no such file: /tmp/report.txt" tells them everything.

Two rules every collector here follows:

1. **Never infer success from the absence of an error.** That is the bug this library
   exists to catch. Look at the thing itself.
2. **Say what you saw, including on success.** `file exists: /tmp/r.txt (4 bytes)` is
   auditable; `ok` is not.

Collectors are plain functions, so a user adds their own by passing `verifier=` to
`@verified` — no registration, no base class.
"""
from __future__ import annotations

import fnmatch
import json
import os
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any

# Sentinel: json_field(path, key) with no `expected` asserts the key EXISTS, which is a
# different question from "equals None" — and None is a legitimate value to assert.
_ANY = object()


def file_exists(path: str) -> tuple[bool, str]:
    if not os.path.exists(path):
        return False, f"no such file: {path}"
    return True, f"file exists: {path} ({os.path.getsize(path)} bytes)"


def file_absent(path: str) -> tuple[bool, str]:
    """For deletions — 'I removed the temp files' is a claim like any other."""
    if os.path.exists(path):
        return False, f"file still exists: {path} ({os.path.getsize(path)} bytes)"
    return True, f"confirmed absent: {path}"


def file_contains(path: str, needle: str) -> tuple[bool, str]:
    if not os.path.exists(path):
        return False, f"no such file: {path}"
    body = open(path, encoding="utf-8", errors="replace").read()
    if needle not in body:
        return False, f"file exists but does not contain {needle!r}; output: {body[:120]!r}"
    return True, f"file contains {needle!r} ({os.path.getsize(path)} bytes)"


def http_ok(url: str, expect_status: int = 200, contains: str = None) -> tuple[bool, str]:
    """Confirm an endpoint really responded — 'I posted the webhook' is checkable."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "stepproof/0.1"})
        with urllib.request.urlopen(req, timeout=15) as r:
            status, body = r.status, r.read(4096).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code} from {url}"
    except Exception as e:
        return False, f"request to {url} failed: {e}"
    if status != expect_status:
        return False, f"HTTP {status} from {url}, expected {expect_status}"
    if contains and contains not in body:
        return False, f"HTTP {status} but body lacks {contains!r}; output: {body[:120]!r}"
    return True, f"HTTP {status} from {url}" + (f", body contains {contains!r}" if contains else "")


def sqlite_row_exists(db: str, table: str, where: str = "1=1") -> tuple[bool, str]:
    """The check that catches 'task scheduled successfully' with no scheduler row.

    `where` is interpolated, so it must come from YOUR code, never from model output —
    same rule as any other SQL you would write by hand.
    """
    if not os.path.exists(db):
        return False, f"no such database: {db}"
    try:
        con = sqlite3.connect(db)
        n = con.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]
        con.close()
    except Exception as e:
        return False, f"query failed on {db}: {e}"
    if not n:
        return False, f"no row in {table} where {where} (count 0)"
    return True, f"{n} row(s) in {table} where {where}"


def file_newer_than(path: str, seconds: float = 300) -> tuple[bool, str]:
    """Was this file written RECENTLY — i.e. by the action that just claimed to write it?

    `file_exists` cannot catch the commonest silent failure in a rerun: the agent "regenerated
    the report", the write failed, and yesterday's file is still sitting there. Existence
    passes. Freshness does not.
    """
    if not os.path.exists(path):
        return False, f"no such file: {path}"
    age = time.time() - os.path.getmtime(path)
    if age > seconds:
        return False, (f"file is STALE: {path} last modified {age:.0f}s ago, "
                       f"expected within {seconds:.0f}s — it was not rewritten")
    return True, f"file written {age:.0f}s ago: {path} ({os.path.getsize(path)} bytes)"


def dir_has_files(path: str, min_count: int = 1, pattern: str = "*") -> tuple[bool, str]:
    """Confirm an action that was supposed to produce N outputs actually produced them."""
    if not os.path.isdir(path):
        return False, f"no such directory: {path}"
    found = fnmatch.filter(os.listdir(path), pattern)
    if len(found) < min_count:
        return False, (f"{path} has {len(found)} file(s) matching {pattern!r}, "
                       f"expected at least {min_count}: {found[:5]}")
    return True, f"{len(found)} file(s) matching {pattern!r} in {path}: {found[:5]}"


def json_field(path: str, key: str, expected: Any = _ANY) -> tuple[bool, str]:
    """Check a value inside a JSON file. `key` is dotted: "server.port".

    Config edits are the class of action where "it said it did" is least trustworthy and
    easiest to check — so check it.
    """
    if not os.path.exists(path):
        return False, f"no such file: {path}"
    try:
        data = json.load(open(path, encoding="utf-8"))
    except Exception as e:
        return False, f"{path} is not readable JSON: {e}"

    cur = data
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False, f"{path} has no key {key!r} (stopped at {part!r})"
        cur = cur[part]
    if expected is _ANY:
        return True, f"{key} = {cur!r} in {path}"
    if cur != expected:
        return False, f"{key} is {cur!r} in {path}, expected {expected!r}"
    return True, f"{key} = {cur!r} in {path}"


def command_output(command: str, contains: str = None,
                   expect_code: int = 0) -> tuple[bool, str]:
    """Run a command and check it. Uses a real shell, so redirects behave as written.

    Note the contrast with the demo's broken tool: `shell=True` is exactly what that code
    was missing. Only pass commands YOUR code composes — never a string built from model
    output.
    """
    try:
        p = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
    except Exception as e:
        return False, f"command failed to run: {e}"
    out = (p.stdout or "").strip()
    if p.returncode != expect_code:
        return False, (f"exit {p.returncode} (expected {expect_code}); "
                       f"stdout: {out[:100]!r} stderr: {(p.stderr or '').strip()[:100]!r}")
    if contains and contains not in out:
        return False, f"exit {p.returncode} but output lacks {contains!r}; output: {out[:120]!r}"
    return True, f"exit {p.returncode}; output: {out[:120]!r}"


def output_contains(result: str, needle: str) -> tuple[bool, str]:
    """Check the tool's OWN output — weaker evidence than looking at the world, and the
    docstring says so on purpose. Use it when there is no external state to inspect
    (a pure computation), not as a shortcut when there is."""
    text = str(result or "")
    if needle not in text:
        return False, f"output does not contain {needle!r}; output: {text[:120]!r}"
    return True, f"output contains {needle!r}"
