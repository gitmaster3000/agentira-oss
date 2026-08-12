# Contributing to Agentira

Agentira runs its own development on Agentira. The backlog you'd be working from is a
live Agentira board, worked by the same mix of humans and agents the product is for.
That's unusual, so this document is mostly about the parts that differ from a normal
repo.

## Where work lives

**GitHub Issues** — bug reports, feature ideas, questions. Anyone, no account needed
beyond GitHub. Start here.

**The Agentira board** — the canonical backlog, sprints, and task assignment. It lives
on a hosted Agentira instance rather than in GitHub Projects. If you want to take real
work rather than drive-by fixes, open an issue saying so and a maintainer will create
an account for you. You'll get the same board, the same tasks, and the same agents the
maintainers use.

You don't need board access to send a pull request. You do need it to be assigned
something.

## Before you write code

1. **Get it running.** [the self-hosting guide](https://gitmaster3000.github.io/agentira-oss-docs/technical/self-hosting) boots the stack from
   a clean clone. If it doesn't work for you, that's a bug worth reporting on its own —
   the cold-start path is the one we most want to keep honest.
2. **Read [CLAUDE.md](CLAUDE.md).** It's the code ruleset, written for AI agents and
   equally binding on humans. The parts people trip over:
   - **No direct DB calls in services.** Reads and writes go through a per-domain repo
     module (`backend/forge/repos/*.py`). Services compose; repos own the SQL.
   - **Tests run on Postgres, never SQLite.** Use the shared `pg` / `seed_admin`
     fixtures. Don't build your own engine or `sessionmaker`.
   - **New domains get their own module** (`backend/<domain>.py`), not another function
     appended to `services.py`.
   - **Prompts are configuration.** Agent system prompts live on `Profile.system_prompt`,
     task content on `Task.description`. No prompt text hardcoded in dispatch code.
3. **Write the failing test first.** A behavior change without a test is unfinished.

## Making a change

```bash
git checkout -b fix/short-description
# write the failing test, watch it fail for the right reason, then make it pass
python -m pytest backend/tests/ -q       # needs Docker running
cd frontend && npx vite build            # if you touched the UI
```

Commit messages follow conventional commits — `feat:`, `fix:`, `docs:`, `chore:`,
`ci:`, `test:`. Reference the board key when there is one: `fix(daemon): AP-412 …`.

Keep changes surgical. Touch what the change needs and nothing adjacent. If you spot
unrelated dead code, say so in the PR — don't delete it in the same diff.

## Pull requests

Open against `main`. CI must be green: unit tests, compose-config validation, and an
integration smoke that boots the backend and MCP. Comment `/integration-test` on the PR
to run the full suite with the CLI installed.

A good PR body says what changed, why, and how you verified it. "Tests pass" is not
verification — name the test, or paste the command output. We check.

Reviews come from maintainers and, increasingly, from the Reviewer agent. Agent review
comments are advisory; a human makes the merge call.

## Plain language is a product rule, not a preference

Agentira's audience is founders, small software houses, and solo builders — **not git
or infra experts**. Anything user-facing (UI labels, settings, run badges, warnings,
error text) stays in plain language by default. Technical internals — branch names,
base points, git mechanics, daemon details — go behind an optional "Advanced /
technical" reveal.

A non-engineer product owner must be able to see the same honest status an engineer
does, in words they understand. This applies to every feature, every time.

## Autonomy is transparent or it isn't shipped

Any mechanism that decides task movement or approval must be:

1. declared in workflow configuration (YAML / gates),
2. evaluated through the gate and evidence engine,
3. recorded in the transition and gate-evaluation tables with an evidence snapshot,
4. surfaceable in the UI.

No hidden heuristics — no string-matching on comment text, no inferring intent from
move history. If a decision can't be seen in the UI or the audit trail, it can't be
steered or trusted, and it doesn't go in. This is the whole concept, not a nice-to-have.

## Security

Don't open a public issue for a vulnerability. Email the maintainer address on the
GitHub profile of this repository's owner with a description and reproduction steps.

Two standing cautions, since Agentira runs code on your machine:

- **Sandbox enforcement is Phase 2.** Sandbox modes are configured and logged today but
  not enforced per-runtime. An agent can touch what your user account can touch.
- **Never commit a real credential**, even to a test fixture. Fake addresses
  (`bob@x.io`, `@agentira.local`, `acme.dev`) are the convention.

## License

By contributing you agree your contributions are licensed under
[Apache-2.0](LICENSE), the same license as the project.
