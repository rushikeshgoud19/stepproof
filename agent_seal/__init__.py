"""agent-seal — prove what your agent actually did.

Every observability tool for agents answers "was the output good?". This one answers
"did the action actually happen?" — a different axis, and the one audit frameworks are
converging on.

    from agent_seal import verified

    @verified(proves="file exists at {path}")
    def write_report(path): ...
    # raises VerificationError if the claimed effect isn't in real state

Why it matters, concretely: an agent calls a shell tool that runs `echo DONE > out.txt`
with shlex.split and no shell. The redirect becomes a literal argument, echo prints the
text, exit code 0. The tool honestly reports success. The agent honestly reports success.
An output-level judge reads that and passes it. The file does not exist. Nobody lied —
the gap is between "the tool returned 0" and "the effect exists", and only step-level
verification against real state can see it.
"""
from .collectors import (command_output, dir_has_files, file_absent, file_contains,
                         file_exists, file_newer_than, http_ok, json_field,
                         output_contains, sqlite_row_exists)
from .ledger import GENESIS, Ledger, Seal
from .narration import explain, is_narration
from .verify import VerificationError, get_ledger, report, set_ledger, verified

__version__ = "0.1.0"
__all__ = [
    "verified", "VerificationError", "report",
    "Ledger", "Seal", "GENESIS", "get_ledger", "set_ledger",
    "is_narration", "explain",
    "file_exists", "file_absent", "file_contains", "file_newer_than", "http_ok",
    "sqlite_row_exists", "dir_has_files", "json_field", "command_output", "output_contains",
]
