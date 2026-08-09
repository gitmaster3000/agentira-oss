# Attachment MCP tools

Agentira exposes three attachment tools: `create_attachment`,
`read_attachment`, and `delete_attachment`. This replaces five overlapping
task/project/read/download tools with one create-read-delete (CRD) surface and
adds epic support without growing the MCP tool catalog.

## Contract

### Create

Call `create_attachment` with `filename`, file data, and exactly one owner:

- `task_id` creates a task attachment. Task keys such as `AP-506` are accepted.
- `project_id` creates a project attachment.
- `epic_id` creates an epic attachment.

Use `content` for UTF-8 text. Use `content_base64` only when binary bytes must
travel through MCP. `content_type` defaults to `application/octet-stream`.
For large binary files, use the matching REST multipart endpoint instead:
`/api/tasks/{id}/attachments`, `/api/projects/{id}/attachments`, or
`/api/epics/{id}/attachments`.

### Read

Call `read_attachment` with exactly one identifier:

- `attachment_id` returns one attachment. Text is returned in `content` when
  it is safe to inline. Binary and oversized text return metadata,
  `download_url`, and an authenticated curl hint.
- `task_id`, `project_id`, or `epic_id` returns the attachments owned by that
  resource. Project lists retain the existing small-text `inline_text` field.

### Delete

Call `delete_attachment(attachment_id=...)`. It returns `true` after the row
and persisted file have been removed.

## Validation and authorization

Create and scoped reads reject missing or ambiguous owner parameters. A read
also rejects a mix of `attachment_id` and an owner ID. IDs are never guessed:
the parameter name is the scope discriminator.

Every operation uses the authenticated MCP actor:

- owner-based create/read resolves the task, project, or epic and checks
  project access with the requested read/write level;
- attachment-ID read/delete resolves the attachment to its owning project
  before authorizing;
- denials use the standard generic project-access error so resource metadata
  is not disclosed.

No MCP handler queries the database directly. It calls the existing service
authorization boundary and attachment domain functions.

## Split-service storage behavior

In hosted deployments the MCP and backend services do not share a filesystem.
When `AGENTIRA_API_BASE_URL` is configured, scoped create/read and delete calls
are proxied to the existing authenticated REST routes with the caller's bearer
token. This keeps the backend volume authoritative and prevents orphaned files.
Local development without that variable uses the existing in-process service
and attachment functions.

## Migration from the legacy tools

| Legacy call | Replacement |
|---|---|
| `upload_attachment(task_id=..., ...)` | `create_attachment(task_id=..., ...)` |
| `list_attachments(task_id=...)` | `read_attachment(task_id=...)` |
| `list_project_attachments(project_id=...)` | `read_attachment(project_id=...)` |
| `read_attachment_text(attachment_id=...)` | `read_attachment(attachment_id=...)` |
| `download_attachment(attachment_id=...)` | `read_attachment(attachment_id=...)`, then use `download_url` for binary |

Epic calls use the same create/read tools with `epic_id`. There is no update
operation; delete and recreate an attachment when its contents must change.

## Verification

Unit coverage lives in `backend/tests/test_mcp_attachment_crd.py` and
`backend/tests/test_mcp_attachments_proxy.py`. The first covers the compact tool
surface, scope validation, direct CRD behavior, and member/non-member/wildcard
authorization. The second proves all scope routes and delete operations use the
backend REST service when split-service proxying is enabled.

The Bruno collection under `bruno/mcp/05-attachments/` exercises create/read
for task, project, and epic scopes, reads an individual attachment, and deletes
an attachment through the MCP transport.
