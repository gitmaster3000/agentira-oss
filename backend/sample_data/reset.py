"""Delete everything one org owns (AP-699 --reset). Never touches other orgs.

Generic over the schema so a new org-scoped table is covered automatically:
rows with an `org_id` go by org; org-less child tables (forge_runs,
forge_messages, ...) go via their FK into an org-scoped parent.
"""
from __future__ import annotations

import warnings

from sqlalchemy import Table, delete, select, update
from sqlalchemy.orm import Session

from backend.db import Base
import backend.forge.models  # noqa: F401 — register forge tables on Base

# Nullable FKs that form cycles between org tables; cleared before deleting.
_CYCLE_COLUMNS = [("profiles", "default_project_id"), ("profiles", "runtime_id"),
                  ("forge_agents", "default_project_id"), ("forge_agents", "runtime_id")]


def _org_parents(table: Table) -> list:
    """FK columns of an org-less table that point at an org-scoped table."""
    return [fk.parent for fk in table.foreign_keys
            if "org_id" in fk.column.table.c and fk.column.table.name != "orgs"]


def delete_org(db: Session, org_id: str) -> None:
    tables = Base.metadata.tables
    for tname, col in _CYCLE_COLUMNS:
        t = tables[tname]
        db.execute(update(t).where(t.c.org_id == org_id).values({col: None}))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # cyclic FK sort warning; handled above
        ordered = list(reversed(Base.metadata.sorted_tables))
    for t in ordered:
        if t.name == "orgs":
            continue
        if "org_id" in t.c:
            db.execute(delete(t).where(t.c.org_id == org_id))
            continue
        for fkcol in _org_parents(t):
            parent = next(iter(fkcol.foreign_keys)).column.table
            ids = select(parent.c.id).where(parent.c.org_id == org_id)
            db.execute(delete(t).where(fkcol.in_(ids)))
    db.execute(delete(tables["orgs"]).where(tables["orgs"].c.id == org_id))
    db.commit()
