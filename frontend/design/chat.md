# Chat page — design §2.4 (`is.chat`)

Promotes the floating chat dock into a full-page surface. Global Chat across
every agent.

## Layout
- **Left:** conversation list across all agents — avatar (hashed color), agent
  name, scope label, last-message preview, relative time. Active row highlighted.
- **Right:** conversation pane — header (agent + scope), scrollable message list
  (markdown for assistant turns, plain for user), input with Send / Stop.

## Wiring
| Piece | api.js | Backend route |
|---|---|---|
| Conversation list (across agents) | `forge.listChats()` | `GET /forge/chats` |
| Messages for a conversation | `forge.listMessages(agentId, {scope_key, limit, offset})` | `GET /forge/agents/:id/messages` |
| Send | `forge.sendRuntimeChat(agentId, {content, scope_key})` | `POST /forge/agents/:id/runtime/chat` |
| Stop in-flight turn | `forge.stopChat(agentId, scope_key)` | `POST /forge/agents/:id/chat/stop` |

A conversation is keyed by `(agent_id, scope_key)`. `GET /forge/chats` returns
one row per key, newest first, with `agent_name`, `label`, `last_message`,
`last_used_at` — so the list renders without N per-agent calls.

## Behavior
- Polls the list and the open thread every 3s.
- Windowed message loading: newest 50 as the live tail, older pages fetched on
  scroll-up (shared `lib/chatPagination` helpers).
- First conversation auto-selected on load.

Implementation: `src/pages/Chat.jsx`, route `/chat` (in-shell), sidebar "Chat".
