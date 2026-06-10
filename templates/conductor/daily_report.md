DAILY REPORT.

## Per-project activity (last 24h)
{{PROJECTS}}

## Worker agents
{{AGENTS}}

Write the daily report for the workspace owner as an executive briefing. Output a SINGLE self-contained HTML fragment and nothing else — no preamble, no markdown, no code fences, no <html>/<head>/<body> wrapper. Begin your reply with `<section` and end it with `</section>`.

Structure the report exactly like this:
  <section class="daily-report"> wrapping everything.
  1. An <h1> title and a one-line <p class="subtitle"> with the date.
  2. A <div class="kpis"> row of stat cards — one <div class="kpi"> per headline metric (tasks done, blocked, failed, in-flight, total cost). Each card: <div class="kpi-value">N</div><div class="kpi-label">…</div>.
  3. <h2>Wins</h2> — what got done overnight, as a <ul>.
  4. <h2>Blocked &amp; needs input</h2> — each item and what unblocks it.
  5. <h2>Failing / needs attention</h2>.
  6. <h2>Today's priorities</h2> — an ordered <ol> of 2-3 items.

Use only these tags: section, div, h1, h2, p, ul, ol, li, strong, em, span, table, thead, tbody, tr, th, td. Use the class names above so the dashboard can style it. Do NOT add inline styles or scripts. Lead with the most important thing; be concise and factual.
