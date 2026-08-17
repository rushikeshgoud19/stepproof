"""Seams — prove your agent has the capability before it claims to have used it.

`@verified` answers *"did the action happen?"*. It cannot answer *"did the action exist?"*,
because a capability that silently degrades never produces a step to verify. Nothing runs,
nothing raises, and nothing is written to the ledger — the agent simply reports that there
was nothing to do.

The failure, from real code:

    due = getattr(cron_manager, "peek_due_soon", lambda: [])()

`CronManager` has no `peek_due_soon`. The fallback fired on every tick from the day the
line was written, so the branch returned `[]` forever and the feature it guarded never once
contributed anything. It shipped, ran for months, and looked exactly like a working feature
with nothing to report. Follow the chain:

===========  ==========================  ===============================
layer        says                        and it's telling the truth
===========  ==========================  ===============================
the getattr  "no such attribute"         yes
the fallback ``[]``                      yes — that is what it returns
the branch   "nothing due"               yes — the list really is empty
the agent    "nothing needs attention"   yes — that is what it was handed
===========  ==========================  ===============================

Nobody lies anywhere in the stack. The gap is between *"a name resolved"* and *"something
implements it"*, and no amount of step verification can see it, because there is no step.

A seam closes the gap by refusing to let a consumer outrun a provider:

    seams.declare("cron", "Scheduled task source", methods=("peek_due_soon",))
    seams.provide("cron", CronManager())      # raises: no peek_due_soon
    due = seams.require("cron").peek_due_soon()

Three roles, all required. A *definition* declaring the interface, a *provider*
implementing it, a *consumer* using it. One role alone is not a seam. The term and the
three-role rule are borrowed from deepseek-harness (`docs/capability-seams.md`); the
implementation is not — this is a dict with rules, matching the zero-dependency
constraint of the rest of this package.

Design limits, stated rather than implied:

- Not a dependency-injection container. No scopes, no lifecycle, no injection, no async.
- Duck-typed. ``methods=`` is checked with ``hasattr`` at registration, which catches the
  typo and the wrong object; it does not check signatures.
- ``require()`` raises. A missing provider is a wiring bug, and wiring bugs should be loud
  at the first call rather than silent for a quarter.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Iterable, List, Tuple

__all__ = [
    "Seam", "SeamError", "SeamMissing", "SeamContract", "Seams",
    "declare", "provide", "require", "optional", "has", "graph", "unwired", "report",
]


class SeamError(RuntimeError):
    """Base for every wiring failure. Always a defect in the program, never in the input."""


class SeamMissing(SeamError):
    """A consumer required a seam that nothing provides, or that was never declared."""


class SeamContract(SeamError):
    """A provider does not satisfy the declared interface, or two declarations disagree."""


class Seam:
    """A declared capability: its name, why it exists, and what a provider must offer."""

    __slots__ = ("name", "doc", "methods", "declared_by")

    def __init__(self, name: str, doc: str, methods: Tuple[str, ...], declared_by: str):
        self.name = name
        self.doc = doc
        self.methods = methods
        self.declared_by = declared_by

    def __repr__(self) -> str:
        return f"<Seam {self.name!r} by {self.declared_by}>"


class Seams:
    """A registry of declarations and providers, and the rule that binds consumers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seams: Dict[str, Seam] = {}
        self._providers: Dict[str, Any] = {}
        self._sources: Dict[str, str] = {}
        self._consumers: Dict[str, set] = {}

    # -- definition ---------------------------------------------------------
    def declare(self, name: str, doc: str = "", *, methods: Iterable[str] = (),
                declared_by: str = "?") -> Seam:
        """Declare a capability. Idempotent — modules get imported more than once.

        Re-declaring with a *different* interface raises: two modules disagreeing about
        what a capability is, is the drift this registry exists to catch, and
        last-writer-wins would hide it.
        """
        m = tuple(methods)
        with self._lock:
            existing = self._seams.get(name)
            if existing is not None:
                if existing.methods != m:
                    raise SeamContract(
                        f"seam {name!r} re-declared with a different interface: "
                        f"{existing.declared_by} says {list(existing.methods)}, "
                        f"{declared_by} says {list(m)}")
                return existing
            seam = Seam(name, doc, m, declared_by)
            self._seams[name] = seam
            return seam

    # -- provider -----------------------------------------------------------
    def provide(self, name: str, impl: Any, *, source: str = "?") -> Any:
        """Register the implementation. Validated now, so a typo fails at import time."""
        with self._lock:
            seam = self._seams.get(name)
            if seam is None:
                raise SeamMissing(
                    f"provider registered for undeclared seam {name!r} (from {source}). "
                    f"Declare it first — a provider with no definition is half a seam.")
            missing = [x for x in seam.methods if not hasattr(impl, x)]
            if missing:
                raise SeamContract(
                    f"{source} provides {name!r} with {type(impl).__name__}, which is "
                    f"missing {missing}. Declared interface: {list(seam.methods)}")
            self._providers[name] = impl
            self._sources[name] = source
            return impl

    # -- consumer -----------------------------------------------------------
    def require(self, name: str, *, consumer: str = "?") -> Any:
        """Resolve a capability, or raise.

        This is the line ``getattr(obj, "method", lambda: [])`` should have been.
        """
        with self._lock:
            self._consumers.setdefault(name, set()).add(consumer)
            impl = self._providers.get(name)
            if impl is not None:
                return impl
            seam = self._seams.get(name)
        if seam is None:
            raise SeamMissing(
                f"{consumer} required seam {name!r}, which was never declared. "
                f"Known seams: {sorted(self._seams)}")
        raise SeamMissing(
            f"{consumer} required seam {name!r}"
            f"{' (' + seam.doc + ')' if seam.doc else ''}, declared by "
            f"{seam.declared_by}, but nothing provides it.")

    def optional(self, name: str, default: Any = None, *, consumer: str = "?") -> Any:
        """Resolve if present, else ``default``.

        For capabilities genuinely allowed to be absent — a paid backend with no key.
        Use it only where the caller degrades **on purpose and says so**; reaching for it
        to silence a wiring error rebuilds the bug at the top of this module.
        """
        with self._lock:
            self._consumers.setdefault(name, set()).add(consumer)
            return self._providers.get(name, default)

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._providers

    # -- evidence -----------------------------------------------------------
    def graph(self) -> List[Dict[str, Any]]:
        """Every seam with its provider and its consumers — the capability graph."""
        with self._lock:
            return [{
                "seam": s.name,
                "doc": s.doc,
                "declared_by": s.declared_by,
                "methods": list(s.methods),
                "provider": self._sources.get(s.name),
                "wired": s.name in self._providers,
                "consumers": sorted(self._consumers.get(s.name, ())),
            } for s in sorted(self._seams.values(), key=lambda x: x.name)]

    def unwired(self) -> List[str]:
        """Declared capabilities nothing provides. Check this at startup, not at 3am."""
        with self._lock:
            return sorted(n for n in self._seams if n not in self._providers)

    def report(self) -> str:
        """One line per seam, for a startup log.

        Print it every boot. A capability that quietly lost its provider shows up as
        ``!!`` the next time the process starts, instead of as a feature that mysteriously
        stopped having anything to say.
        """
        rows = self.graph()
        if not rows:
            return "no seams declared"
        out = [f"{len(rows)} seam(s):"]
        for r in rows:
            mark = "OK " if r["wired"] else "!! "
            out.append(f"  {mark}{r['seam']:<28} <- {r['provider'] or 'NOBODY'}"
                       f"   consumers={len(r['consumers'])}")
        return "\n".join(out)


#: The default registry, for programs that only need one.
_DEFAULT = Seams()

declare = _DEFAULT.declare
provide = _DEFAULT.provide
require = _DEFAULT.require
optional = _DEFAULT.optional
has = _DEFAULT.has
graph = _DEFAULT.graph
unwired = _DEFAULT.unwired
report = _DEFAULT.report
