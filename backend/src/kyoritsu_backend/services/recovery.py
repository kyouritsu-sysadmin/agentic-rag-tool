from sqlalchemy import select
from kyoritsu_backend.db.models import GenerationRun, Message, now
from .chat import ACTIVE


async def interrupt_orphaned_runs(sessions):
    async with sessions.begin() as session:
        for run in (
            await session.scalars(select(GenerationRun).where(GenerationRun.status.in_(ACTIVE)))
        ).all():
            run.status, run.error, run.updated_at = (
                "interrupted",
                "API restarted before completion",
                now(),
            )
            (await session.get(Message, run.assistant_message_id)).status = "interrupted"
