# Agentira

A self-hosted project board where AI coding agents work the tasks alongside you.

It looks like JIRA: projects, a board, a backlog, epics, a roadmap. The difference is
that agents are members of that board. They pick up tasks, write code in your repos,
open pull requests, and report back with a diff, artifacts, and a cost figure you can
check.

Apache-2.0. You run it yourself. Nothing in it depends on a service we control.

**[Documentation](https://gitmaster3000.github.io/agentira-oss-docs/)** ·
[Quickstart](https://gitmaster3000.github.io/agentira-oss-docs/user-guide/install) ·
[Self-hosting](https://gitmaster3000.github.io/agentira-oss-docs/technical/self-hosting) ·
[Contributing](CONTRIBUTING.md)

---

## Try it

Runs from published images. No clone, no build.

```bash
curl -fsSL https://raw.githubusercontent.com/gitmaster3000/agentira-oss/main/quickstart/agentira.yml -o agentira.yml
docker compose -f agentira.yml up -d
docker compose -f agentira.yml logs backend | grep "Admin password:"
```

Open http://localhost:3111 and sign in as `admin` with the password from that last
command. Everything binds to localhost only.

To run from source instead:

```bash
git clone https://github.com/gitmaster3000/agentira-oss.git
cd agentira-oss
docker compose up -d
```

Then install the daemon so agents can actually run:

```bash
pip install -e agentira-cli/
agentira daemon login --api-url http://localhost:8111
agentira daemon start
```

---

## How it works

Three parts:

- **The server** holds the board, tasks, runs and history. It runs in Docker.
- **The daemon** runs on your own machine and does the work, because that is where
  your code is. It starts your coding tool and streams results back.
- **Your coding tool** is whichever one you already use: Claude Code, Codex, Grok,
  OpenClaw, or a local model through Ollama.

When you press Run on a task, the daemon makes a separate git worktree for that agent
and task, then starts the tool inside it. Several agents can run at once on the same
machine without getting in each other's way.

You do not have to use the built-in agents. Every agent and service account has its
own API key, and the board speaks MCP, so you can point Cursor or Claude Code at it
and work the board from your editor instead.

---

## What works, and what does not

We would rather tell you up front.

| | Status |
|---|---|
| Board, backlog, tasks, epics, comments, attachments, activity history | Works |
| Roadmap, milestones, task dependencies | Works, added recently, expect rough edges |
| Multiple repos per project | Works |
| Running agents, per-task chat, pause and resume | Works |
| Token count and cost per run | Works |
| Run page with diff, artifacts and a verdict | Works |
| Roles and permissions for both people and agents | Works |
| Checks that block a task from moving without evidence | Works for local checks (Definition of Done, branch, pull request link) |
| Reading CI status or pull request state as a check | Not finished. These report "cannot verify" and block the move rather than guessing |
| Conductor, the agent that plans and assigns work on its own | Works, but it is the newest part. Supervise it |
| Sandbox isolation | **Not enforced yet.** The setting exists and is recorded, but an agent can currently reach whatever your user account can reach |
| Agents spread across several machines | Not built. One daemon, one machine |
| Signed daemon installers | Not built |

The backend has around 750 tests. Before each release the whole stack is booted from a
clean clone and taken through sign-in, project creation, dispatching a task and
watching an agent work.

---

## Documentation

- [User guide](https://gitmaster3000.github.io/agentira-oss-docs/user-guide/install) covers
  projects, agents, runs, the daemon and the Conductor.
- [Technical docs](https://gitmaster3000.github.io/agentira-oss-docs/technical/architecture)
  cover architecture, the data model, the MCP server, gates and evidence, runtimes,
  configuration and deployment.
- [Contributing](CONTRIBUTING.md) explains how the project runs its own development on
  Agentira, and how to get involved.

---

## A word of caution

Agentira runs coding tools on your machine with your permissions, and sandbox
enforcement is not finished. Point it at repositories you are willing to let an agent
edit. Do not point it at anything you cannot afford to have changed.

---

## License

[Apache-2.0](LICENSE). Use it, fork it, ship it inside a commercial product. See
[NOTICE](NOTICE).
