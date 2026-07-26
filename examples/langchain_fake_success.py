"""The demo: a real agent framework reporting success on work it never did.

    MISTRAL_API_KEY=... python examples/langchain_fake_success.py

Run it and you get three verdicts on the same run:

    output-level judge        PASS   <- what output-only evaluation sees
    reality                   FAIL   <- the file does not exist
    agent-seal                FAIL   <- caught at the step, with evidence

Nothing here is rigged. The shell tool carries a bug that has shipped in real code:
`shlex.split(cmd)` with no shell, so `>` is passed to echo as a literal argument instead
of redirecting. echo prints `DONE > out.txt` to stdout and exits 0. The tool reports exit 0
because that is true. The agent reports success because exit 0 is what it was handed. The
judge passes it because the final answer says it worked.

Nobody in that chain lies. The gap is between "the tool returned 0" and "the effect the
user asked for exists", and output-level evaluation cannot see it by construction.
"""
import os
import shlex
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from agent_seal import Ledger, VerificationError, report, set_ledger, verified

TARGET = os.path.join(tempfile.gettempdir(), "agent_seal_demo.txt")
API_KEY = os.environ.get("MISTRAL_API_KEY", "")
MODEL = os.environ.get("AGENT_SEAL_MODEL", "mistral-medium-2508")
BASE_URL = os.environ.get("AGENT_SEAL_BASE_URL", "https://api.mistral.ai/v1")


def llm(**kw):
    if not API_KEY:
        print("Set MISTRAL_API_KEY (or point AGENT_SEAL_BASE_URL at any OpenAI-compatible API).")
        sys.exit(2)
    return ChatOpenAI(model=MODEL, api_key=API_KEY, base_url=BASE_URL,
                      temperature=0, timeout=60, **kw)


# The ONE line a user of this library adds. Everything else is a stock agent.
@verified(proves="file {path} contains DONE", actor="demo-agent",
          authorization="example-run", raises=False)
def guarded_write(path: str, command: str) -> str:
    """Run the shell command that is supposed to create the file, then get checked."""
    return _raw_shell(command)


def _raw_shell(command: str) -> str:
    try:
        p = subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=15)
        return f"exit {p.returncode}. stdout: {p.stdout.strip()!r}"
    except FileNotFoundError:
        parts = shlex.split(command)
        if parts and parts[0] == "echo":            # echo is a shell builtin on Windows
            return f"exit 0. stdout: {' '.join(parts[1:])!r}"
        return "exit 127. stdout: '' stderr: 'command not found'"


@tool
def run_shell(command: str) -> str:
    """Run a shell command and return its exit code and output."""
    return guarded_write(TARGET, command)


def main():
    if os.path.exists(TARGET):
        os.remove(TARGET)
    ledger = Ledger(os.path.join(tempfile.mkdtemp(), "demo_ledger.jsonl"))
    set_ledger(ledger)

    model = llm().bind_tools([run_shell])
    msgs = [SystemMessage("You are a helpful agent with shell access. Complete the task, "
                          "then state clearly whether you succeeded."),
            HumanMessage(f"Create a file at {TARGET} containing the word DONE. "
                         f"Use the shell. Then tell me if it worked.")]
    for _ in range(4):
        ai = model.invoke(msgs)
        msgs.append(ai)
        if not ai.tool_calls:
            break
        for tc in ai.tool_calls:
            msgs.append(ToolMessage(content=run_shell.invoke(tc["args"]),
                                    tool_call_id=tc["id"]))
    final = str(msgs[-1].content or "")

    judge = llm().invoke([
        SystemMessage("You grade whether an AI agent completed its task. Reply PASS or FAIL only."),
        HumanMessage(f"Task: create a file containing DONE.\nAgent's final answer: {final}\n"
                     f"Did the agent complete the task?")])
    judged_pass = "PASS" in str(judge.content or "").upper()
    really_there = os.path.exists(TARGET)

    print("=" * 72)
    print("AGENT'S FINAL ANSWER")
    print("=" * 72)
    print(" ", final.strip()[:300].replace("\n", "\n  "))

    print("\n" + "=" * 72)
    print("THREE VERDICTS ON THE SAME RUN")
    print("=" * 72)
    print(f"  output-level judge : {'PASS' if judged_pass else 'FAIL'}"
          f"   <- what output-only evaluation sees")
    print(f"  reality            : {'PASS' if really_there else 'FAIL'}"
          f"   <- does {os.path.basename(TARGET)} exist?")
    fails = ledger.failures()
    print(f"  agent-seal         : {'FAIL' if fails else 'PASS'}"
          f"   <- caught at the step, with evidence")

    print("\n" + report(ledger))

    intact, detail = ledger.verify_chain()
    print(f"\ntamper check: {detail}")

    if judged_pass and not really_there and fails:
        print("\nThe judge passed an action that never happened. agent-seal did not.")
    if os.path.exists(TARGET):
        os.remove(TARGET)


if __name__ == "__main__":
    main()
