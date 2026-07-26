"""Narration detection — telling a PLAN apart from an OBSERVATION.

When you ask an agent to verify something, it will often reply with what it is *about to*
do ("I'll use the file tool to check...") or with a refusal ("I don't have access to files")
— while holding the very tools it says it lacks. Neither is evidence. Accepting either is
how a verification layer ends up rubber-stamping exactly what it was built to catch.

Both shapes were observed in production, and each caused a different failure:

  NARRATION -> false POSITIVE. A plan reads as confident and gets accepted as a result.
  REFUSAL   -> false NEGATIVE. Work that genuinely completed was reported as 0/2 because
               the checker claimed incapability instead of looking. This direction matters
               just as much: a checker that cries wolf gets ignored, and real failures hide
               behind the noise.

The hard-won detail: `exists` and `contains` are NOT treated as observation markers, because
narration says them too — "I will check if the file exists". An earlier version included them
and therefore missed the precise bug it was written for. Result markers must be things only a
real observation produces: exit codes, `output:`, `no such file`, timestamps.
"""
from __future__ import annotations

import re

_NARRATION_PAT = re.compile(
    r"\b(i will|i'll|i am going to|i'm going to|let me|i would|i can use|i need to use|"
    r"to verify (?:this|the condition)|first,? i|next,? i|i plan to|i'm about to)\b",
    re.IGNORECASE)

_REFUSAL_PAT = re.compile(
    r"(i'?m sorry|i am sorry|i don'?t have (?:the )?(?:capability|access|ability)|"
    r"i cannot (?:access|check|read|verify)|i can'?t (?:access|check|read|verify)|"
    r"unable to (?:access|check|read|verify|interact)|"
    r"as an ai|i don'?t have direct access)", re.IGNORECASE)

# Markers of an ACTUAL observation. Strict on purpose — see the module docstring.
_RESULT_PAT = re.compile(
    r"(exit\s*(?:code)?\s*[:=]?\s*\d|output\s*:|stdout|stderr|no such file|does not exist|"
    r"not found|\d{4}-\d{2}-\d{2}|\d{1,2}:\d{2}\s*(?:AM|PM)?|"
    r"successfully (?:created|scheduled|sent|written)|\btrue\b|\bfalse\b|"
    r"returned\s|status\s*(?:code)?\s*[:=]?\s*\d)", re.IGNORECASE)


def is_narration(text: str) -> bool:
    """True when `text` is a plan or a refusal rather than an observation.

    Only the OPENING is scanned for intent — a reply may reasonably start by restating the
    task — and a concrete observation anywhere in the text rescues it. Short concrete outputs
    ("WORKING", "not found", "exit 0") must pass, since that is precisely what a real command
    returns; an over-eager detector that rejects them is useless in practice.
    """
    t = (text or "").strip()
    if not t:
        return True                              # silence is not evidence
    if _REFUSAL_PAT.search(t[:200]):
        return not _RESULT_PAT.search(t)         # unless it actually reported something
    if _NARRATION_PAT.search(t[:120]):
        return not _RESULT_PAT.search(t)
    return False


def explain(text: str) -> str:
    """Why a piece of 'evidence' was rejected — audit trails need reasons, not verdicts."""
    t = (text or "").strip()
    if not t:
        return "empty: nothing was reported"
    if _REFUSAL_PAT.search(t[:200]) and not _RESULT_PAT.search(t):
        m = _REFUSAL_PAT.search(t[:200])
        return (f"refusal, not evidence: claims incapability ({m.group(0)!r}) without "
                f"reporting any observation")
    if _NARRATION_PAT.search(t[:120]) and not _RESULT_PAT.search(t):
        m = _NARRATION_PAT.search(t[:120])
        return (f"narration, not evidence: states intent ({m.group(0)!r}) and never reports "
                f"a result")
    return "accepted: contains a concrete observation"
