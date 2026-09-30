Your work was approved in review, but merging its pull request failed, so
nothing was merged. The platform checked the pull request's merge result with
the project's checks and asked GitHub to merge it; the failure is below.

Fix it on your task branch: bring in the latest base branch, make the
project's checks pass (run the project's verify command), commit, and push to
the SAME branch — the existing pull request updates by itself, do not open a
new one. Then finish your run as succeeded. It will go back through review.

Failure:

{{REVIEW}}
