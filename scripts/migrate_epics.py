import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.db import Base, SessionLocal
from backend.models import Project, Task, Epic
from backend import services

def migrate():
    db = SessionLocal()
    
    # We will convert these tags into epics
    tags_to_convert = [
        "epic:workspace-execution", 
        "epic:trigger-system", 
        "epic:production-safety", 
        "epic:runs-foundation", 
        "epic:run-observability", 
        "epic:studio-ui",
        "frontend",
        "backend",
        "infrastructure"
    ]
    
    colors = ["#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#6366f1", "#8b5cf6", "#ec4899", "#14b8a6", "#f97316"]
    epic_cache = {} # (project_id, tag) -> epic_id
    
    tasks = db.query(Task).all()
    count = 0
    for task in tasks:
        if not task.tags:
            continue
        
        task_tags = [t.strip() for t in task.tags.split(',') if t.strip()]
        for tag in tags_to_convert:
            if tag in task_tags:
                tag_name = tag.replace("epic:", "").replace("-", " ").title()
                
                # Create epic if not exists for this project
                cache_key = (task.project_id, tag)
                if cache_key not in epic_cache:
                    # Check DB first
                    existing = db.query(Epic).filter(Epic.project_id == task.project_id, Epic.title == tag_name).first()
                    if existing:
                        epic_cache[cache_key] = existing.id
                    else:
                        color = colors[len(epic_cache) % len(colors)]
                        epic = Epic(
                            title=tag_name, 
                            project_id=task.project_id, 
                            color=color,
                            description=f"Auto-migrated from tag: {tag}"
                        )
                        db.add(epic)
                        db.commit()
                        db.refresh(epic)
                        epic_cache[cache_key] = epic.id
                
                # Assign epic_id and remove tag
                task.epic_id = epic_cache[cache_key]
                task_tags.remove(tag)
                task.tags = ",".join(task_tags) if task_tags else ""
                db.commit()
                count += 1
                break # Only one epic per task

    print(f"Migrated {count} tasks to Epics.")
    db.close()

if __name__ == "__main__":
    migrate()
