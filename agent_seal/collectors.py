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

import os
import sqlite3
import urllib.error
import urllib.request


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
        req = urllib.request.Request(url, headers={"User-Agent": "agent-seal/0.1"})
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


def output_contains(result: str, needle: str) -> tuple[bool, str]:
    """Check the tool's OWN output — weaker evidence than looking at the world, and the
    docstring says so on purpose. Use it when there is no external state to inspect
    (a pure computation), not as a shortcut when there is."""
    text = str(result or "")
    if needle not in text:
        return False, f"output does not contain {needle!r}; output: {text[:120]!r}"
    return True, f"output contains {needle!r}"
