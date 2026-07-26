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

## Seal a whole agent, not one function

```python
from agent_seal.adapters.langchain import seal_tools       # or .openai_agents, or .crewai

tools = seal_tools(tools)                                        # record everything
tools = seal_tools(tools, proves={"run_shell": "file exists at {path}"})   # and verify
```

Three adapters, one API: **LangChain**, **OpenAI Agents SDK**, **CrewAI**. Each imports its
framework lazily, so `import agent_seal` never requires any of them.

In CrewAI especially, pass `actor=` when sealing per agent — crews delegate, the same tool
gets invoked by several agents, and *who authorized this* is the audit question that becomes
impossible to answer after the fact.

`seal_tools(tools)` on its own **does not mark anything verified**. It records what was
called, with which arguments, and what came back — and leaves the verdict blank, reported
as `never checked`. Calling an unchecked action "verified" because nothing threw is the
exact mistake this library is about.

That is also the honest way to adopt it: point it at an agent you already have, run your
normal workload, then read `report()` to find out how much of what it does is actually
confirmed. Add `proves=` for the actions that matter.

## Evidence clauses

```
"file exists at {path}"
"no file at {path}"                                  # deletions are claims too
"file {path} contains {text}"
"file {path} written within 300s"                    # catches the rerun that did nothing
"http 200 from {url}"                                # ... containing {text}
"sqlite {db} has row in {table} where {clause}"      # catches "task scheduled!" with no row
"dir {path} has 3 files matching *.png"
"json {path} has server.port = 8001"                 # or just: json {path} has server.port
```

**Freshness is the one people forget.** `file exists` passes on yesterday's file, so an
agent that "regenerated the report" while the write silently failed still looks successful.
Existence is not freshness, and a rerun is exactly where that gap hides.

`{...}` is filled from the wrapped function's own arguments, so the contract is written once
at the definition. Referencing an argument the function doesn't take raises immediately
rather than quietly verifying nothing.

Anything the grammar can't express takes a callable instead — an unreadable clause is worse
than a function:

```python
@verified(verifier=lambda **kw: (queue.depth() == 0, f"queue depth {queue.depth()}"))
def drain_queue(): ...
```

A verifier that returns prose instead of an observation is rejected by the narration
detector, so a lazy checker can't rubber-stamp itself.

## Install

```bash
pip install -e .
python tests/test_agent_seal.py                  # 28 checks — core, ledger, tamper
python tests/test_collectors_and_adapter.py      # 37 checks — collectors, clause grammar
python tests/test_adapters.py                    # 42 checks — all three adapters
python tests/test_collectors_extra.py            # 31 checks — freshness, dir, json, shell
```

No pytest, and the core has **no dependencies at all** — a verification library that is
annoying to verify, or that drags a framework into your stack, is a poor advertisement for
itself.

## Status

Early but real. Built and tested: the decorator, hash-chained ledger with tamper detection,
narration detector, evidence collectors (file / freshness / dir / json / http / sqlite /
shell), the clause grammar, adapters for LangChain / OpenAI Agents SDK / CrewAI, and the
audit report. **138 checks pass**, and
`import agent_seal` pulls in zero third-party modules.

Next: PyPI, and collectors for whatever people actually verify.

Extracted from a personal AI assistant whose verification layer exists because it once
reported a task as scheduled that it had never scheduled.

## License

MIT
