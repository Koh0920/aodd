# AODD — Agent Operation Driven Development

A development practice that places **a stuck agent's operation log**, not a failing test, at the center of the loop.

```text
TDD:  test fails       → implement → test passes
AODD: agent operates   → inspect   → improve product → agent completes naturally
      (and gets stuck)
```

The deliverable is not `pass / fail`. It is a **Usecase Receipt**: a structured record of how an autonomous user actually experienced the product — where they hesitated, retried, guessed, or gave up.

This repository ships AODD as a portable [Claude Code](https://docs.claude.com/en/docs/claude-code) skill. The methodology itself is tool-agnostic.

## What's in here

- [`SKILL.md`](./SKILL.md) — the full methodology, formatted as a Claude Code skill (frontmatter + body). Read this first.
- [`LICENSE`](./LICENSE) — MIT.

## The five principles

1. **Real Surface First** — operate through the same surface a real user touches.
2. **Getting Stuck Is Signal** — friction is product input, not test failure.
3. **Receipts Over Assertions** — record the full transcript, not just `pass/fail`.
4. **Operator and Inspector Are Separate** — the agent that operates the product must not also inspect server internals or edit code during a run.
5. **Completion Is Not Enough** — finishing while retrying / guessing / accepting risky prompts is `degraded`, not `complete`.

See [`SKILL.md`](./SKILL.md) for the full cycle, role split (Operator / Inspector / Fixer), Usecase Receipt format, and CI integration notes.

## Install as a Claude Code skill

User scope (available everywhere on your machine):

```bash
mkdir -p ~/.claude/skills/aodd
curl -fsSL https://raw.githubusercontent.com/Koh0920/aodd/main/SKILL.md \
  -o ~/.claude/skills/aodd/SKILL.md
```

Project scope (only this repo):

```bash
mkdir -p .claude/skills/aodd
curl -fsSL https://raw.githubusercontent.com/Koh0920/aodd/main/SKILL.md \
  -o .claude/skills/aodd/SKILL.md
```

Once installed, invoke it explicitly with `/aodd`, or describe a task that matches its trigger (e.g. *"run an agent through the signup flow as a first-time user and tell me where it gets stuck"*).

## When to use AODD

Use it for:

- Agent-driven UX evaluation
- End-to-end feasibility checks for real users
- Finding usability and onboarding frictions an agent (or first-time user) actually hits
- Prioritizing fixes by what blocks autonomous completion

Do **not** use it for:

- Unit-test authoring
- Pure regression coverage of known flows (use E2E tests)
- One-shot bug fixes with a known repro

## Status

AODD is a proposed development practice, not a fixed framework. Feedback, dissent, and prior-art pointers are welcome via Issues.

## License

MIT — see [`LICENSE`](./LICENSE).
