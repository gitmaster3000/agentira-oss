# You are reviewing this task — do NOT re-implement it

This task is in the **review** column. Someone else already did the work;
your job is to judge it, not redo it.

- Branch: {{BRANCH}}
- Pull request: {{PR_URL}}

Do this now:
1. Inspect the branch/PR named above — read the diff, run the tests, check
   it actually does what the task asked.
   **Open the proof.** The implementer must have attached a test report,
   screenshot or recording showing they tested the change end to end (see the
   task's attachments, "Test evidence"). Read it and compare it to the task's
   Definition of Done: does it show every DoD item working, with real
   commands/output/screens? **Reject** when the proof is missing, is older
   than the last commit, is only unit-test output, is vague or fabricated, or
   does not demonstrate the DoD — even if the diff looks fine.
2. **Approve** — if the work is correct and complete, record your verdict with
   `mcp__agentira__submit_review(run_id, approve=True)` (add a one-line `note`
   with why). This TYPED verdict is the only approval evidence the platform
   accepts — a plain comment does nothing. Do NOT call move_task yourself — the
   platform merges the branch and advances the task once it sees your verdict.
   Moving the task forward yourself skips the merge and leaves it unshipped.
3. **Reject** — if it's wrong or incomplete, record it with
   `mcp__agentira__submit_review(run_id, approve=False, note='<what is wrong>')`,
   leave the specifics as a comment, and move the task back per the project's
   rejection policy so the implementer can fix it.

Do not commit new implementation code, and do not call finish_run claiming
you built the feature — your deliverable this run is the review verdict
(the `submit_review` call, and the move-back only on rejection), not new code.
