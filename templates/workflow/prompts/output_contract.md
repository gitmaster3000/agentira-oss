## Output contract — do NOT skip this
A task is only "succeeded" if there is something the human can
look at when they open the Run page. Before calling finish_run
with outcome="succeeded":

1. **Commit your changes** in the worktree you're in. The Run page's
   Changes tab reads from `git diff` — if you didn't commit, the
   page shows nothing and the work looks lost.
2. **Push your branch** to origin: `git push -u origin <your-branch>`.
   Unpushed work is invisible to review and integration — the merge
   step reads the shared clone/remote, not your private worktree.
3. **Open a pull request** against the project's base branch
   ({{BASE_BRANCH}}) and link it on the task. Nothing is merged without a
   pull request, so work without one is not finished:
   `gh pr create --base {{BASE_BRANCH}} --head <your-branch> --title "<task title>" --body "<what changed and why>"`,
   then call mcp__agentira__update_task with `pr_url` set to the pull
   request's address (…/pull/<number>). Never target any other branch and
   never merge it yourself — review and the platform merge it.
4. **Verify before you claim.** A commit hash in your summary is only
   true if `git cat-file -t <hash>` succeeds, and "pushed" is only true
   if `git ls-remote origin | grep <your-branch>` shows it. Run both and
   include the output in your success comment. Never state a hash or a
   push you did not verify — review checks exactly this and will reject.
5. **Check off the Definition of Done.** For every DoD item you
   actually completed, call mcp__agentira__update_task with the full
   dod_items list and `checked: true` on the items you finished. The
   board's review gate requires all DoD items checked before the task
   can advance to review — leave unfinished items unchecked and say so
   in your summary. Do NOT check an item you didn't truly complete; a
   reviewer verifies your work next.
6. **Register at least one artifact** via
   mcp__agentira__register_run_artifact for the deliverable —
   the pull request URL (kind="pr" — required for work that will
   be merged), a generated report (kind="report"),
   a deployed preview (kind="url"), or a key file (kind="file").
   This is what shows up in the "Here's what got built" panel
   on the Run page. No artifact = the human can't tell what you did.

If you didn't actually produce a deliverable, **do NOT pretend you
did**. Call finish_run with outcome="blocked" (and a real
explanation in summary) or outcome="failed" instead.

When you finish, call mcp__agentira__finish_run with:
  - run_id: "{run_id}"
  - outcome: one of "succeeded" | "blocked" | "needs_input" | "failed"
  - summary: one paragraph describing what changed (or what's blocking).
Use "blocked" when you can't proceed without external input
(missing credentials, ambiguous spec, broken dependency).
