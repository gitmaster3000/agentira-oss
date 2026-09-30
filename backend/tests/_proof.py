"""Test helper: attach proof (a test report) to a task row."""

from backend.models import Attachment


def add_proof(db, task_id: str, kind: str = "test-report") -> None:
    db.add(Attachment(task_id=task_id, filename="proof.md", kind=kind,
                      file_path="proof.md", uploaded_by="test-agent"))
    db.commit()
