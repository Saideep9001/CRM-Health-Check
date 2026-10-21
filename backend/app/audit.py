"""Activity log for admins: sign-ins and every change to people, roles and access."""
import uuid

from sqlalchemy.orm import Session

from .models import AuditEventRow


def who(person) -> str:
    """'Name <email>' for a Principal or a UserRow."""
    return f"{person.name} <{person.email}>"[:255]


def record(db: Session, actor: str, action: str, target: str | None = None, detail: str | None = None) -> None:
    """Add an entry; it's saved with the caller's commit."""
    db.add(AuditEventRow(id=str(uuid.uuid4()), actor=actor[:255], action=action[:40], target=(target or None) and target[:255],
                         detail=(detail or None) and detail[:500]))
