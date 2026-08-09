# AP-506 manual test: unified attachment MCP CRD

## Purpose

Verify that the three attachment MCP tools route task, project, and epic IDs to
the correct owner, return text without a base64 round trip, delete persisted
files, and enforce project access.

## Preconditions

1. Start Agentira with the backend and MCP endpoints reachable.
2. Sign in as a project member and initialize an MCP session in Bruno.
3. Open the `bruno/mcp/05-attachments` collection folder.

## Happy-path test

Run the requests in sequence order. Confirm:

1. The project, task, and epic setup requests each return an ID.
2. `create_attachment(task_id=...)` returns only the matching `task_id`.
3. `read_attachment(attachment_id=...)` returns the task file's UTF-8 body in
   `content` and does not return `content_base64`.
4. `read_attachment(task_id=...)` lists the task attachment.
5. `create_attachment(project_id=...)` returns only the matching `project_id`;
   the project-scoped read lists it and includes its small Markdown body as
   `inline_text`.
6. `create_attachment(epic_id=...)` returns only the matching `epic_id`; the
   epic-scoped read lists it.
7. `delete_attachment(attachment_id=...)` returns `true`.
8. The cleanup request deletes the temporary project.

## Validation test

Call `create_attachment` once without an owner ID and once with both `task_id`
and `project_id`. Call `read_attachment` once without an ID and once with both
`attachment_id` and `task_id`. Each call must fail with an "exactly one" error
and must not create or disclose an attachment.

## Authorization test

Repeat a scoped read and an attachment-ID read/delete using an authenticated
user who is not a project member. Each operation must fail with the generic
`Project resource not found or access denied` response. It must not reveal the
owner type, project name, filename, or file contents. Repeat with a wildcard
administrator and confirm the read/delete succeeds.

## Split-service persistence test

With `AGENTIRA_API_BASE_URL` configured and MCP/backend running as separate
services, create a text attachment, restart only the MCP service, then read and
delete the attachment. The read must still return the backend-stored content,
and the backend download URL must return 404 after deletion. This confirms the
MCP service did not rely on its own ephemeral filesystem.
