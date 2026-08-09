# Design reference

Source design system (Claude Design): hash `NsuYkUUnCSH1wYzViG-FlQ`,
file `Agentira.dc.html`. The shell chrome (`src/components/shell/AppSidebar.jsx`)
is a verbatim port of design hash `RjjZ09618cpj5TzJmourRQ`.

The original `.dc.html` prototype is hosted on claude.ai/design and is not a
writable project for this workspace, so it can't be vendored byte-for-byte here.
What lives in this folder is the **design-derived spec** each screen is built
against — the same spec the AP-277 UI→backend wiring plan was authored from.

- [`chat.md`](./chat.md) — global Chat page (design §2.4), implemented in AP-287.
