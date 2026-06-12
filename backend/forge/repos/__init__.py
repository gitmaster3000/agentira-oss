"""Per-domain data-access layer (CLAUDE.md: services compose; repos own the
SQL). New orchestration code must read/write through these modules — direct
`db.query(...)` in services/drivers is legacy, migrated as it's touched."""
