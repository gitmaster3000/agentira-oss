# Conventions

Use Ruff. All commits must be on a feature branch.

## Project authorization

- Every project-owned REST or MCP operation must receive the authenticated
  actor and enforce `backend.auth.require_project_access`.
- Resolve indirect IDs (task, epic, attachment, run, repo, artifact) to their
  owning project before reading or mutating them.
- Constrain list queries by `project_ids_for_actor`; never load protected rows
  and filter them in a client or serializer.
- Membership grants ordinary project read/write only. Cross-project read,
  cross-project write, membership administration, and system administration
  require separate explicit permissions.
- Return a generic 403 for denials and log denied actor/action/project details
  server-side without returning protected metadata.
- Add member, non-member, wildcard-admin, direct-ID, indirect-ID, MCP, and REST
  regression tests for every new project-scoped surface.
- Run `ruff check` and the relevant security tests before committing.
