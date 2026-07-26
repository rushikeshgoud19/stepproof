# agent-seal

**Prove what your agent actually did.**

Every observability tool for agents answers *"was the output good?"*. `agent-seal` answers
*"did the action actually happen?"*

```python
from agent_seal import verified

@verified(proves="file {path} contains DONE")
def write_report(path):
    ...
# raises VerificationError if the claimed effect isn't in real state
```

---

## The failure this exists for

Run [`examples/langchain_fake_success.py`](examples/langchain_fake_success.py) and you get
three verdicts on the same run:

```
output-level judge : PASS   <- what output-only evaluation sees
reality            : FAIL   <- the file does not exist
agent-seal         : FAIL   <- caught at the step, with evidence
```

The agent said:

> I succeeded in creating the file at `…/agent_seal_demo.txt` containing the word **DONE**.

The file was never created.

**Nothing in that demo is rigged.** The shell tool carries a bug that has shipped in real
code: `shlex.split(cmd)` executed without a shell, so `>` is passed to `echo` as a literal
argument instead of redirecting. `echo` prints `DONE > out.txt` to stdout and exits `0`.

Follow the chain:

| layer | says | and it's telling the truth |
|---|---|---|
| the tool | `exit 0` | yes — that is genuinely what happened |
| the agent | "I succeeded" | yes — exit 0 is what it was handed |
| the judge | `PASS` | yes — the final answer does say it worked |

**Nobody lies anywhere in the stack.** The failure lives entirely in the gap between *"the
tool returned 0"* and *"the effect the user asked for exists"* — and output-level evaluation
cannot see that gap **by construction**, not by oversight.

Research puts a number on it: agents evaluated only on final-output quality pass **20–40%
more test cases** than trajectory-level evaluation reveals. Roughly one in three passing
agents is broken.

## What you get

**`@verified(proves=...)`** — run the action, then check real state. Mismatch raises by
default, because a verification layer that only logs is one more thing nobody reads. Pass
`raises=False` to sweep an existing agent and find out how much of what it reports is real.

**A hash-chained ledger** — every seal carries the hash of the one before it. Edit a record
and its own hash stops matching; delete one and the next record's `prev_hash` points at
nothing. `verify_chain()` names which record broke and how. Plain JSONL, no dependencies —
an audit artifact you can't read without the tool that wrote it isn't worth much.

```python
led.verify_chain()
# (False, "record 0 ('pay') was modified after sealing: contents hash to a3f…")
```

**A narration detector** — the piece with no equivalent elsewhere. Ask an agent to verify
something and it will often reply with a *plan* ("I'll use the file tool to check…") or a
*refusal* ("I don't have access to files") while holding the very tools it says it lacks.
Neither is evidence.

```python
is_narration("I will check if the file exists.")   # True  - a plan
is_narration("I don't have access to files.")      # True  - a refusal
is_narration("exit 0")                             # False - an observation
```

Both directions matter. Narration accepted as evidence is a **false positive**. A refusal
treated as failure is a **false negative** — work that genuinely completed reported as
broken, which is how a checker earns a reputation for crying wolf and gets ignored.

Hard-won detail: `exists` and `contains` are deliberately *not* observation markers, because
narration says them too — *"I will check if the file **exists**"*. An earlier version counted
them and therefore missed the exact bug it was written to catch.

**Actor and authorization on every seal** — audit frameworks want to know *who authorized
this*, not just what happened.

## Install

```bash
pip install -e .
python tests/test_agent_seal.py     # 27 checks, no pytest needed
```

## Status

Early. The core is built and tested: decorator, hash-chained ledger, tamper detection,
narration detector, audit report. Framework adapters (LangChain, OpenAI Agents SDK, CrewAI)
are next — the demo uses LangChain directly today.

Extracted from a personal AI assistant whose verification layer exists because it once
reported a task as scheduled that it had never scheduled.

## License

MIT
