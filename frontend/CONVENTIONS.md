# agentira-frontend conventions

Read this before adding UI. The codebase follows **Material Design 3** loosely, with the canonical component classes defined in `src/index.css` under the `MD3 Components` layer. **Don't reinvent button/input styles inline.** Reach for the token classes below first; if you need a variant, add it to `index.css` so it's reusable.

## Button hierarchy

| Use | Class | When |
|---|---|---|
| Primary action | `btn btn-primary` | The main action of a screen / modal (e.g. *Create Project*, *Save Changes*, *New Service Account*). Accent-filled, MD3 elevation on hover. Icon optional inside via `<Plus className="w-4 h-4"/>`. |
| Secondary action | `btn btn-ghost` | Cancel buttons, dismissive actions. Transparent bg, accent-colored text. |
| Inline edit (Pencil) | `p-0.5 text-text-tertiary hover:text-text-secondary transition-colors` + `<Pencil className="w-3 h-3"/>` | Tiny icon-only button next to an editable field. Triggers an inline `<input>` swap. See `TaskDetailPanel.jsx` branch/pr_url for the canonical pattern. |
| Inline copy | Same as above but with `<Copy/>` + `hover:text-accent-primary` | Copy-to-clipboard next to a value. Use `<Check className="text-green-500"/>` for the brief "copied!" confirmation state. |
| Destructive | `text-red-400 hover:text-red-300 p-2 rounded hover:bg-red-500/10` | Delete buttons. Icon-only with `<Trash2 className="w-4 h-4"/>`. NEVER use `.btn-primary` for destructive — confusing. |
| Small action chip | `text-[10px] px-2 py-1 rounded bg-white/5 hover:bg-white/10 flex items-center gap-1` | Compact row actions where `.btn` would dominate. Used in service-account rows, file attachment rows, etc. |

**Never** write `bg-purple-600 hover:bg-purple-500 rounded text-white` inline for a primary button. That's just `.btn .btn-primary`. The accent color is theme-token-driven; hard-coding purple breaks dark/light or future re-themes.

## Inline editing pattern

Used for renaming, editing single-field values without a modal. Canonical examples: `TaskDetailPanel.jsx` (branch, pr_url, title); `Settings.jsx` (service-account name).

Required pieces:
1. **State**: `const [editingX, setEditingX] = useState(false); const [xValue, setXValue] = useState(initial);`
2. **Pencil icon button** next to the value: `<button onClick={() => setEditingX(true)}><Pencil className="w-3 h-3"/></button>`
3. **Click value to edit** (optional but encouraged): the value itself is `<button onClick={() => setEditingX(true)}>{value}</button>`
4. **Input swap**: `{editingX ? <input autoFocus value={xValue} onChange={…} onBlur={commit} onKeyDown={Enter→commit, Esc→cancel} /> : <span>{value}</span>}`
5. **Commit**: PATCH the resource, await reload, `setEditingX(false)`. Empty/whitespace input = no-op cancel.

Do **not** open a modal for renaming a single field. Modals are for multi-field creation flows or destructive confirmations.

## Modals

- **Create flows** (multi-field): `CreateProjectModal.jsx`, `CreateTaskModal.jsx`, `CreateAgentModal.jsx`. Use the existing `fixed inset-0 z-50 bg-black/50 backdrop-blur-sm` overlay pattern. Form fields use `.input`. Primary submit = `.btn .btn-primary`.
- **Destructive confirmation**: `ConfirmModal.jsx`. Use `isDanger` prop; the button becomes red automatically.
- **Single-value prompt**: avoid. Use inline editing instead.

## Inputs

- `.input` — the canonical outlined text field. Rounded-xl, focus state, theme-aware. Use it for ALL text/number/email inputs and `<select>` (it carries the `appearance: none` reset).
- Multi-line: `<textarea className="input min-h-[120px]" />`.
- Search/filter pills/compact inputs: prefer `text-xs py-1 px-2` overrides on top of `.input`, not custom classes.

## Color tokens

Theme is HSL-token driven via CSS vars. **Always use the token variables**, never hex colors:
- `var(--accent-primary)` / `var(--accent-subtle)` / `var(--accent-on)` — brand interactive
- `var(--text-primary)` / `var(--text-secondary)` / `var(--text-tertiary)` — text hierarchy
- `var(--bg-app)` / `var(--bg-panel)` / `var(--bg-hover)` — surface tiers
- `var(--border-subtle)` / `var(--border-active)` — outlines

Tailwind utilities map to these via the `theme.extend.colors` config (`text-text-primary`, `bg-bg-panel`, `border-border-subtle`). Use the utilities when possible.

## Icons

`lucide-react` only. Sizing convention:
- `w-3 h-3` — inline action icons (edit, copy, small delete)
- `w-4 h-4` — header/nav icons, button-internal icons
- `w-5 h-5` — primary visual icons inside avatar circles
- `w-8 h-8 opacity-20` — empty-state placeholder icons

## When in doubt

Find a similar surface that already exists, copy its structure. The codebase's three canonical surfaces to reference:
- **TaskDetailPanel** — for editable rows, inline fields, action button hierarchy
- **CreateTaskModal** — for create-flow modals
- **Settings.jsx** — for list-of-rows-with-actions UIs
