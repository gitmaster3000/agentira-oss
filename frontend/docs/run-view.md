# Run view layout (RunDetail)

The Run page (`/forge/runs/:runId`, `src/pages/forge/RunDetail.jsx`) was
reordered so the conversation is the first thing you read and the deep
technical diagnostics are tucked at the bottom.

## What changed

### Conversation moved to the top, and is now bounded
The **Conversation** card used to sit below the metrics grid, the "Where it
ran" diagnostics, the timeline and the trigger event — you had to scroll past
all of that to see what the agent actually said. It now renders right under the
status header (after the summary/error banners), so it's the first content
block on the page.

The conversation is also **bounded — no infinite scroll**:

- Only the most recent turns are rendered (`previewEvents`, default cap 8),
  inside a fixed-height box (`max-h-[420px] overflow-y-auto`). The page no
  longer grows without limit as a long-running agent streams hundreds of
  messages.
- When older turns are dropped, a one-line hint shows the count:
  *"N earlier messages hidden — open in chat for the full thread."*
- The full, send-able thread is one click away. When the run has a task and an
  agent, the whole card links to the combined chat area
  (`/forge/agents/:agentId?tab=chat&scope=task:<taskId>`) — the same
  read-only-thread-becomes-send-able behaviour as before, now framed as the
  place the *complete* conversation lives.

### "Where it ran" moved to the bottom
The **Where it ran** diagnostics card (`RunDiagnostics` — workdir, worktree
branch, claude session id, log paths, freshness badge) moved from the middle of
the page to the very bottom, after the Details card. It's deep operator detail
you reach for when something went wrong, not the first thing a human needs.

### Order on the page now
1. Status header + run controls
2. Ready checks / prompt editor (READY runs only)
3. Artifacts ("here's what got built")
4. Summary / Error banners
5. **Conversation** (bounded preview → click to open the combined chat)
6. Metrics grid
7. Timeline
8. Trigger event
9. Trace ids
10. Details
11. **Where it ran** (diagnostics)

## `previewEvents` helper
Pure, exported, unit-tested (`RunDetail.test.jsx`):

```js
previewEvents(events, limit = 8) // → { shown, hiddenCount }
```

Returns the last `limit` events (most recent tail) and how many older ones were
hidden. Null/empty input → `{ shown: [], hiddenCount: 0 }`.

## Manual test
1. Open a run with several messages: `/forge/runs/<id>`.
2. Confirm the Conversation card appears near the top (under the status header),
   before the metrics grid.
3. Confirm "Where it ran" is the last card on the page.
4. For a run with >8 messages: confirm only the most recent ~8 render, the box
   scrolls internally at a fixed height (the page itself doesn't grow with the
   thread), and the "N earlier messages hidden" hint shows.
5. Click the Conversation card → lands in the combined agent chat scoped to the
   run's task. (For runs without a task/agent the card is non-clickable, as
   before.)

## Security note
Frontend-only, presentational change. No new data is fetched or exposed —
`previewEvents` slices the already-loaded `events` array client-side, and the
chat link reuses the existing scoped route. No new inputs, network calls, auth,
or storage paths. No change to what the API returns or who can read it.
