# Your agent passes its evals because your evals only check the output

*Draft — for HN / r/LocalLLaMA / r/MachineLearning / dev.to. Rushi edits before posting.*

---

I asked a LangChain agent to create a file. It said:

> I succeeded in creating the file at `/tmp/report.txt` containing the word **DONE**.

An LLM judge read that answer and marked the task **PASS**.

The file did not exist.

Here is the thing that bothers me about it: **nothing in that stack lied.**

---

## The tool was honest

The agent had one shell tool. Roughly this:

```python
@tool
def run_shell(command: str) -> str:
    """Run a shell command and return its exit code and output."""
    p = subprocess.run(shlex.split(command), capture_output=True, text=True)
    return f"exit {p.returncode}. stdout: {p.stdout.strip()!r}"
```

Spot it? `shlex.split` with no `shell=True`. So when the agent ran:

```
echo DONE > /tmp/report.txt
```

`>` was not a redirect. It was passed to `echo` as a literal argument. `echo` printed
`DONE > /tmp/report.txt` to stdout and exited **0**.

The tool reported `exit 0` — true, that is exactly what happened.
The agent reported success — true, `exit 0` is what it was handed.
The judge returned PASS — true, the final answer does say it worked.

Every layer was honest. The file still isn't there.

I didn't invent that bug for a blog post. I shipped it, in my own assistant, and it took me
weeks to notice — because everything downstream of it looked green.

## Why output-level evaluation cannot catch this

Look at what the judge actually receives: **a string**. The agent's final answer. It has no
access to the filesystem, the database, or the API the agent supposedly called. Asking it
"did the agent complete the task?" is asking it to grade a claim against nothing.

That isn't a weak judge or a bad prompt. A judge that only sees the output cannot detect a
failure that is invisible in the output. It's structural.

The research already put a number on this: agents evaluated only on final-output quality
pass **20–40% more test cases** than trajectory-level evaluation reveals. Roughly one in
three "passing" agents is broken somewhere you aren't looking.

And the tooling reflects the blind spot. LangSmith, Arize, Braintrust — they trace, they
score, they let you compare prompts. What none of them do is go and check whether the action
actually happened.

## The uncomfortable version

Everyone can tell you what an agent **said**. Almost nobody can prove what it **did**.

If your agent writes files, sends messages, updates rows, calls webhooks — how many of those
effects have you confirmed *since the demo*? Not "did the call return 200". Did the row
appear.

## What I built

[`stepproof`](https://github.com/rushikeshgoud19/stepproof). One decorator:

```python
from stepproof import verified

@verified(proves="file {path} contains DONE")
def write_report(path):
    ...
# VerificationError: write_report reported 'Report written successfully.'
# but 'file /tmp/report.txt contains DONE' is not true: no such file
```

Run the action, then go look at real state. Seal both the claim and the evidence.

Same demo, three verdicts on one run:

```
output-level judge : PASS   <- what output-only evaluation sees
reality            : FAIL   <- the file does not exist
stepproof         : FAIL   <- caught at the step, with evidence
```

Three things in it are worth more than the decorator.

**Freshness, not just existence.** `file exists` passes on yesterday's file. So an agent that
"regenerated the report" while the write silently failed still looks successful. `"file
{path} written within 300s"` catches the rerun that did nothing — and in my experience that
is the single commonest silent failure in anything scheduled.

**A narration detector.** Ask an agent to verify something and it will often reply with a
*plan* — "I'll use the file tool to check…" — or a *refusal* — "I don't have access to
files" — while holding the exact tool it says it lacks. Neither is evidence.

```python
is_narration("I will check if the file exists.")   # True  - a plan
is_narration("I don't have access to files.")      # True  - a refusal
is_narration("exit 0")                             # False - an observation
```

Both directions cost you. Narration accepted as evidence is a false positive. A refusal
counted as failure is a false negative — I had a job that genuinely completed reported as
0/2, which is worse than useless, because a checker that cries wolf gets ignored and then
the real failures hide behind the noise.

One detail I got wrong first: I treated "exists" and "contains" as evidence markers. But
narration says them too — *"I will check if the file **exists**"* — so the detector sailed
straight past the exact bug it was written for. The markers have to be things only a real
observation produces: exit codes, `output:`, `no such file`, timestamps.

**A hash-chained ledger.** Each seal carries the hash of the one before it. Edit a record and
its own hash stops matching; delete one and the next record's `prev_hash` points at nothing.

```python
ledger.verify_chain()
# (False, "record 0 ('pay') was modified after sealing: contents hash to a3f…")
```

Plain JSONL, no dependencies. An audit artifact you can't read without the tool that wrote it
isn't worth much.

## Using it on an agent you already have

```python
from stepproof.adapters.langchain import seal_tools   # or .openai_agents, or .crewai

tools = seal_tools(tools)     # record every call
```

That alone marks nothing as verified. It records what was called, with what arguments, what
came back — and leaves the verdict blank, counted as `never checked`. Calling an unchecked
action "verified" because nothing threw is the exact mistake the library exists to catch, and
I wasn't going to commit it in the adapter.

Then run your normal workload and read the report. The number that matters is how much of
what your agent reports is actually confirmed. Mine was lower than I expected.

## Where it's honest about itself

It's early — 0.1.0. Core is dependency-free, 138 tests, adapters for LangChain / OpenAI
Agents SDK / CrewAI. The clause grammar covers files, freshness, directories, JSON, HTTP and
sqlite; anything else takes a callable.

It cannot verify what you can't observe. If an action has no checkable effect, this gives you
a trail and an honest "never checked", not a verdict. That's the point — I'd rather it say
*I don't know* than hand you another green check you haven't earned.

It came out of a personal assistant that once told me a task was scheduled when it had never
called the scheduler. I found that by accident. I did not want to find the next one by
accident.

---

**Repo:** https://github.com/rushikeshgoud19/stepproof
**The demo:** `examples/langchain_fake_success.py` — run it and watch the judge pass an
action that never happened.

If you try it on a real agent, I'd genuinely like to know what percentage came back
unverified. That number is the whole argument, and I only have my own.
