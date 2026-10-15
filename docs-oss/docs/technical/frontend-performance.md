# Frontend performance rules

Target: any keystroke or click paints in under 50 ms, and a dropdown shows its options on the first frame. Users sit 100–150 ms from the server, so a fetch on open is always visible. These rules are enforced by lint (`npm run lint`, run in CI) and by render-count tests.

For the request side (one request path, dedupe, polling) see [Architecture → Frontend](./architecture.md#frontend). For measuring real users, see [Browser telemetry](./client-telemetry.md).

## 1. Typing state lives in the input

A text field's draft belongs in a small component (`CommentComposer`, `DescriptionEditor`, `TitleEditor`), not in a page or panel root. Lift the value only on submit, save or blur. Typing must never re-render the page.

Bad — `TaskPage.jsx` keeps `comment` in the page root and passes `comment`/`setComment` down to `CommentsSection`, so every keystroke re-renders the whole page:

```jsx
const [comment, setComment] = useState('');          // page root
<CommentsSection comment={comment} setComment={setComment} … />
```

Good — the composer owns its draft; the page only sees the submitted text:

```jsx
function CommentComposer({ onSubmit }) {
    const [draft, setDraft] = useState('');
    return <textarea value={draft} onChange={(e) => setDraft(e.target.value)} … />;
}
```

## 2. No fetch on open for data an ancestor has

Modals, drawers, menus and selects get their options (members, epics, statuses, profiles) as props or context from `ProjectLayout` or `useShellData`. Options must exist when the control opens. Never render an empty select and fill it later.

Bad — `CreateTaskModal.jsx` fires four requests in a mount effect (members, epics, project, the full task list with descriptions) that the project page already loaded:

```jsx
useEffect(() => {
    api.getProjectMembers(projectId).then(setProfiles);
    api.getEpics(projectId).then(setEpics);
    api.listTasks(projectId).then(setProjectTasks);
}, [projectId]);
```

Good — read what the ancestor already has:

```jsx
const { members, epics } = useOutletContext();   // from ProjectLayout
```

## 3. Lazy-load only what is not on screen yet

Load it on first use (focus or open), not on mount. Never download a full list (every task with its description) just to compute suggestions; request only the fields needed. Heavy views use `React.lazy`, like `RoadmapView`.

## 4. Memoize heavy renders

Markdown, long lists, activity and comment feeds, and charts are wrapped in `React.memo` with stable props: `useCallback` for handlers, `useMemo` for derived arrays. Derived data over large arrays (tags, filters, matches) goes in `useMemo`.

Bad — `components/Markdown.jsx` re-parses the whole markdown tree every time its parent renders, even with identical text.

Good:

```jsx
export const Markdown = React.memo(function Markdown({ children, className = '' }) { … });
```

## 5. Polls must not re-render when nothing changed

Compare a cheap key (`updated_at`, length, last id) before `setState`, and keep object identity when equal:

```jsx
setActivities((prev) => (prev.length === next.length && prev.at(-1)?.id === next.at(-1)?.id ? prev : next));
```

## 6. Small components

A new or touched page or component stays under about 400 lines. Split by section instead of passing 30 props into one tab.

## What lint enforces

| Rule | Level | Why |
|---|---|---|
| `react-hooks/rules-of-hooks` | error | Hooks called conditionally break state. |
| `react-hooks/exhaustive-deps` | error | Missing deps cause stale data; extra effects cause refetch loops. |
| `max-lines` 400 (`src/pages`, `src/components`) | warning, CI runs with `--max-warnings 0` | Rule 6. |
| `no-restricted-syntax` on `fetch(` / `axios` | error | Rule: go through `api.request()`. Allowed only in `api.js` and `telemetry.js`. |

Existing violations are listed in `frontend/eslint.config.js` (`MAX_LINES_ALLOW_LIST`, `EXHAUSTIVE_DEPS_ALLOW_LIST`), each tagged `TODO(AP-698)`. The list may only shrink: fix a file, then delete its entry. New code that breaks a rule fails CI. Do not add a file to a list to get a PR through.

## Render-count tests

`frontend/src/test/renderCount.jsx` counts renders so a test can assert rule 1:

```jsx
const rc = renderCount();
render(<Page rc={rc} />);   // Page renders <rc.Probe id="page" /> and wraps Composer in <rc.Profile id="composer">
rc.reset();
type('hello');
expect(rc.count('composer')).toBeLessThanOrEqual(5);   // at most N renders for N characters
expect(rc.count('page')).toBe(0);                      // page root never re-renders
```

- `rc.Profile` counts commits of its subtree: use it around the component under test.
- `rc.Probe` counts its own renders: create it inline in the JSX of the component that must not re-render. Do not pass a pre-built `<rc.Probe/>` element as a prop; React skips unchanged elements and it would never count.

See `frontend/src/test/renderCount.test.jsx` for a passing example and a failing-pattern example.
