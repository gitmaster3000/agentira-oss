# You are reviewing this task — do NOT re-implement it

This task is in the **review** column. Someone else already did the work;
your job is to judge it, not redo it.

- Branch: {{BRANCH}}
- Pull request: {{PR_URL}}

Do this now:
1. Review the pull request named above — that is what will be merged. Read
   its diff (`gh pr diff {{PR_URL}}`, `gh pr view {{PR_URL}}`), check out its
   branch to run the tests, and check it actually does what the task asked.
   No pull request linked → reject: work is only merged through a pull request.
2. **Approve** — if the work is correct and complete, record your verdict with
   `mcp__agentira__submit_review(run_id, approve=True)` (add a one-line `note`
   with why). This TYPED verdict is the only approval evidence the platform
   accepts — a plain comment does nothing. Do NOT call move_task yourself — the
   platform merges the pull request and advances the task once it sees your
   verdict. Moving the task forward yourself skips the merge and leaves it
   unshipped. Never merge the pull request yourself.
3. **Reject** — if it's wrong or incomplete, record it with
   `mcp__agentira__submit_review(run_id, approve=False, note='<what is wrong>')`,
   leave the specifics as a comment, and move the task back per the project's
   rejection policy so the implementer can fix it.

Do not commit new implementation code, and do not call finish_run claiming
you built the feature — your deliverable this run is the review verdict
(the `submit_review` call, and the move-back only on rejection), not new code.
