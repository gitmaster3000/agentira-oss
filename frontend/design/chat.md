# Chat page — design §2.4 (`is.chat`)

Promotes the floating chat dock into a full-page surface. Global Chat across
every agent.

## Layout
- **Left:** agent list — **one row per agent** (not one row per conversation),
  avatar (hashed color), agent name, the agent's most-recent message preview +
  relative time, and a "N conversations" hint when the agent has more than one
  scope. Active agent highlighted; header shows the total agent count.
- **Right:** conversation pane — header with agent + a **per-agent
  "Conversation" selector** (dropdown that switches between that agent's scoped
  chats), scrollable message list (markdown for assistant turns, plain for
  user), input with Send / Stop.

## Wiring
| Piece | api.js | Backend route |
|---|---|---|
| Conversation list (across agents) | `forge.listChats()` | `GET /forge/chats` |
| Messages for a conversation | `forge.listMessages(agentId, {scope_key, limit, offset})` | `GET /forge/agents/:id/messages` |
| Send | `forge.sendRuntimeChat(agentId, {content, scope_key})` | `POST /forge/agents/:id/runtime/chat` |
| Stop in-flight turn | `forge.stopChat(agentId, scope_key)` | `POST /forge/agents/:id/chat/stop` |

A conversation is keyed by `(agent_id, scope_key)`. `GET /forge/chats` returns
one row per key, newest first, with `agent_name`, `label`, `last_message`,
`last_used_at`. The page **groups these rows by `agent_id`** client-side to
render the agent rail (newest-first) and to populate each agent's conversation
selector — so the list still renders without N per-agent calls.

## Behavior
- Polls the list and the open thread every 3s.
- Windowed message loading: newest 50 as the live tail, older pages fetched on
  scroll-up (shared `lib/chatPagination` helpers).
- The newest agent's most-recent conversation is auto-selected on load; picking
  an agent opens its most-recent scope; the top selector switches scopes.

Implementation: `src/pages/Chat.jsx`, route `/chat` (in-shell), sidebar "Chat".
