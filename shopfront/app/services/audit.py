from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def record_audit(db: AsyncSession, action: str, entity_id: int) -> None:
    db.add(AuditLog(action=action, entity_id=entity_id))
    await db.flush()
