# ADR 005: Service Accounts for Agent Identity

## Context
We need to support AI agents interacting with the system.
- Agents need stable credentials (API Keys).
- Agents need to be distinguishable from human users.
- Agents need to be able to set their own "personality" (name/avatar).
- Humans need control over agent access (provisioning/revocation).

## Decision
We implement a **Service Account** model with **Agent Self-Configuration**.

### 1. Service Accounts (Bots)
- **Definition**: A `Profile` with `role="bot"`.
- **Creation**: Explicitly created by a human via `POST /api/service-accounts`.
- **Credential**: An `api_key` is generated at creation time and returned to the human.
- **Management**: Humans can list and revoke (delete) these accounts via Settings.

### 2. Agent Autonomy
- **Authentication**: Agents use the provided `api_key` to authenticate via MCP.
- **Self-Configuration**: Agents can call `update_profile` tool to set their own `display_name` and `avatar_url`. This allows a generic "Bot" to become "Code Assistant" upon first run.

### 3. Separation of Concerns
- **Identity Provisioning**: Handled by Humans (Security).
- **Identity Configuration**: Handled by Agents (Personality).
- **No Open Signup**: The `signup` tool is removed from MCP to prevent unauthorized account creation.

## Consequences
- **Pros**:
    - Secure: No open signup.
    - Controllable: Humans own the keys.
    - Flexible: Agents can still have unique identities.
- **Cons**:
    - Manual step: Humans must generate a key before an agent can run. (This is a desired feature for security).

## Verification
- `tests/test_agent_identity.py` validates the entire lifecycle.
