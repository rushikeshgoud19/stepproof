# Release checklist — v0.1.0

Everything here is free. No paid account is needed at any step.

## Decide first (blocks step 2 only)

- [ ] **Name.** `stepproof` is free on PyPI and GitHub. Note `agentseal` v0.10.0 exists —
      a *different* package (AI-agent security scanning), different normalized name, so both
      can coexist. The cost is confusion and search leakage in the same niche.
      Renaming is cheap until the moment we publish. Available alternatives checked
      2026-07-27: `stepproof`, `verifact`, `proofkit`, `did-it`.

## 1. GitHub (do this first)

Stars are the Stage-2 kill metric and they only exist here. The post must point at something
people can star.

```bash
cd ~/OneDrive/Desktop/stepproof
gh repo create stepproof --public --source=. --remote=origin \
  --description "Prove what your agent actually did. Step-level verification + a tamper-evident audit trail."
git push -u origin master
```

- [ ] Add topics: `ai-agents`, `llm`, `verification`, `observability`, `evaluation`, `audit`,
      `langchain`, `crewai`
- [ ] Confirm the README renders — the three-verdict block is the hook, it must be visible
      without scrolling
- [ ] `examples/langchain_fake_success.py` runs from a clean clone

## 2. PyPI

Do this **after** the name is final: a version number can never be reused, and yanking is messy.

```bash
python -m build                      # produces dist/stepproof-0.1.0-*.whl + .tar.gz
python -m twine upload dist/*        # needs a free PyPI account + API token
```

Verified already on 2026-07-27:
- wheel builds clean and ships exactly the 9 modules, nothing stray
- installs into a clean venv with **zero** dependencies
- `@verified` catches a fake success from that clean install

- [ ] Free PyPI account + API token (`pypi.org/manage/account/token`) — **Rushi does this
      part.** Claude does not create accounts or handle credentials; hand over the token
      via `twine` on your own machine, or run the upload yourself.
- [ ] `pip install stepproof` in a fresh venv, run the smoke snippet from the README

## 3. The post

Draft: [`docs/launch-post.md`](launch-post.md). Rushi edits before posting — a launch post
that reads as machine-written undercuts a library about honesty.

- [ ] Read it out loud once. Cut anything that sounds like marketing.
- [ ] Post order: dev.to or a blog first (a stable link), then HN, then
      r/LocalLLaMA and r/MachineLearning
- [ ] HN title: plain and specific. *"Your agent passes its evals because your evals only
      check the output"* — no "Show HN: revolutionary…"
- [ ] Be around for the first two hours to answer comments. That matters more than the timing.

## Kill criterion

**<100 stars and zero unsolicited users after 10 weeks → the pain is real but you're not the
one who gets to solve it. Pivot.**

Write the date here when the post goes live: ____________
Ten weeks from that date: ____________

Track honestly. The whole library is about not accepting a claim without evidence; the
project's own traction gets the same treatment.
