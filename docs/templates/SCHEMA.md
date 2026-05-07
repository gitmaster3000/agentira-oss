# Workflow Template Schema (v1)

> **What is a workflow template?** A YAML file that defines a complete project
> type — its board columns, agent roster, gate checks, and conductor strategy
> — without any platform code changes. One template = one product flavor
> (Production Readiness, SEO Audit, SAP Onboarding, etc.).
>
> See AGENTIRA_VISION.md §4 for the rationale.

---

## File location

Templates live as YAML files in `templates/` at the repo root. The filename
(without `.yaml`) is the template id used elsewhere:

```
templates/
  production-readiness.yaml   ← id: "production-readiness"
  seo-audit.yaml              ← id: "seo-audit"
  sap-onboarding.yaml         ← id: "sap-onboarding"
```

Templates ship in the repo for v1. A template marketplace is explicitly out
of scope (see vision §11).

---

## Top-level keys

```yaml
name: string                  # human-readable name
version: string               # semver, this template's own version
description: string           # one-paragraph explainer

trigger:                      # what kind of input creates a project
  type: string                #   github_repo_url | website_url | document | brief_text
  label: string               #   UI prompt shown to the user

columns: list<string>         # board columns, ordered left to right

agents: list<Agent>           # the agent roster (see Agent below)

ac_check_types: list<ACCheck> # named gate-check types (see ACCheck below)

conductor: Conductor          # auto-pick / auto-assign behavior
```

All top-level keys are required except `description` and `trigger.label`.

---

## `Agent`

```yaml
- name: string                # unique within this template (e.g. "Auditor")
  role: string                # one of the standard roles (see below)
  model: string               # default model — agent runtime resolves it
  system_prompt_file: string  # relative path under prompts/<template-id>/
  allowed_tools: list<string> # MCP tool names this agent may call
  container_image: string?    # optional — Step 6+ (container isolation)
```

### Standard roles

Per AGENTIRA_VISION §7.1. Templates may use any subset.

| Role          | Purpose                          |
|---------------|----------------------------------|
| auditor       | Analyze + report, no writes      |
| planner       | Create remediation issues        |
| implementer   | Write code via PR                |
| reviewer      | Review PRs (different model from implementer) |
| deployer      | Provision infra, deploy          |
| conductor     | Orchestrate (no human-visible role) |

### `allowed_tools`

Names match the MCP tools registered on the Agentira MCP server
(`backend/mcp_server.py`). Common entries:

- `claim_task`, `move_task`, `update_task`, `add_comment`, `block_task`
- `create_task`, `delete_task`
- `link_pr`, `attach_file`
- `read_repo`, `get_task`, `list_tasks`

A `null` (omitted) `allowed_tools` means **no restriction** during
development. Production templates SHOULD specify an allowlist.

### Cross-model review (vision §7.2)

If a template uses both `implementer` and `reviewer`, their `model` MUST
differ. The loader rejects the template otherwise.

---

## `ACCheck` (gate-check type)

A reusable runner definition. Tasks reference these by name in their AC
list (added in Step 4).

```yaml
- name: string              # unique within this template
  description: string
  runner: string            # shell command to execute
  pass_condition: string    # expression evaluated against runner output
  timeout_sec: int          # optional, default 60
```

### `runner`

A shell command. Can include `{placeholder}` parameters that the AC instance
fills in (e.g. `pytest {test_name}`). The runner executes in the project's
working directory.

### `pass_condition`

A small expression DSL evaluated against the runner's output. Supported
references:

- `exit_code` — process exit code (int)
- `output` — stdout (string)
- `output_lines` — number of non-empty lines in stdout (int)
- `{placeholder}` — same placeholders as in `runner`

Supported operators: `==`, `!=`, `<`, `>`, `<=`, `>=`, `&&`, `||`,
parentheses, string equality.

Examples:

```yaml
pass_condition: "exit_code == 0"
pass_condition: "output_lines == 0"
pass_condition: "exit_code == 0 && output == '{expected_status}'"
```

The DSL is intentionally tiny. If a check needs richer logic, write a
custom runner script and check `exit_code`.

### Bundled examples

```yaml
ac_check_types:
  - name: test_passes
    description: Named test passes
    runner: "pytest {test_name} --tb=short"
    pass_condition: "exit_code == 0"

  - name: no_secrets_in_source
    description: No hardcoded secrets detected
    runner: "trufflehog filesystem . --json"
    pass_condition: "output_lines == 0"

  - name: file_exists
    description: Required file exists
    runner: "test -f {path}"
    pass_condition: "exit_code == 0"
```

---

## `Conductor`

```yaml
conductor:
  auto_assign: bool           # auto-assign unblocked tasks to free agents
  pick_strategy: string       # "highest_priority_unblocked" | "fifo"
  respect_dependencies: bool  # honor task dependencies
  notify_on_block: bool       # emit notification when an agent blocks
  digest_schedule: string     # "daily" | "hourly" | "off"
```

All fields are optional with sensible defaults. The full AGENTIRA_VISION §4
schema is supported; new strategies land here additively.

---

## Validation rules

The loader rejects a template when any of these fail:

1. `version` is not a valid semver string.
2. `columns` has fewer than 2 entries or contains duplicates.
3. An `agent.role` is not a standard role.
4. An `agent.system_prompt_file` does not exist on disk.
5. `implementer.model == reviewer.model` (cross-model review rule).
6. An `ac_check_types` entry is referenced but not defined.
7. A `runner` references a `{placeholder}` not present in any AC instance.
   *(Loose check; warn-only in v1.)*

---

## Library + parsing decision

**Library:** PyYAML (already in many backend deps; minimal footprint).

**Validation:** Pydantic v2 models. We already use Pydantic for FastAPI
request bodies, and the validation errors are first-class. The alternative
(jsonschema) is more verbose for the same coverage and produces less
readable errors.

**Loader entry point** (Step 3 work, not v1):

```python
from backend.templates.loader import load_template
template = load_template("templates/production-readiness.yaml")
# → Template object validated by Pydantic
```

The Pydantic models live at `backend/templates/schema.py`. Schema-as-code
is the source of truth; this document mirrors it.

---

## What v1 explicitly does not include

- Template inheritance / `extends:` (defer until needed)
- Conditional agents (`if: workspace.has_python`)
- Per-environment overrides (`production:` / `staging:`)
- Skill libraries / shared prompt fragments
- Container image build instructions
- `trigger.config` schemas beyond `type` + `label`

Each is additive. Add them when a real template would benefit.

---

## See also

- `AGENTIRA_VISION.md` §3 (universal workflow), §4 (template example), §7 (roles)
- `backend/templates/schema.py` (Pydantic models — Step 3)
- `templates/production-readiness.yaml` (canonical example)
