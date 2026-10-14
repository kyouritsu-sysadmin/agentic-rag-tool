from sqlalchemy import select, delete
from kyoritsu_backend.core.errors import ApplicationError
from kyoritsu_backend.db.models import Thread, Message, GenerationRun
from kyoritsu_backend.db.repositories import owned_thread, branch_messages, message_sources
from kyoritsu_backend.schemas.serialization import thread_dict, run_dict, message_dict
from kyoritsu_backend.services.chat import ACTIVE


class ThreadService:
    def __init__(self, sessions):
        self.sessions = sessions

    async def create(self, body, principal):
        async with self.sessions.begin() as session:
            thread = Thread(owner_id=principal.subject, title=body.title)
            session.add(thread)
            await session.flush()
            return thread_dict(thread)

    async def list(self, principal, offset=0, limit=50):
        async with self.sessions() as session:
            rows = list(
                (
                    await session.scalars(
                        select(Thread)
                        .where(Thread.owner_id == principal.subject)
                        .order_by(Thread.created_at.desc(), Thread.id)
                        .offset(offset)
                        .limit(limit + 1)
                    )
                ).all()
            )
            return {
                "threads": [thread_dict(t) for t in rows[:limit]],
                "next_offset": offset + limit if len(rows) > limit else None,
            }

    async def patch(self, thread_id, body, principal):
        async with self.sessions.begin() as session:
            thread = await owned_thread(session, thread_id, principal, lock=True)
            if await session.scalar(
                select(GenerationRun.id).where(
                    GenerationRun.thread_id == thread_id, GenerationRun.status.in_(ACTIVE)
                )
            ):
                raise ApplicationError(
                    409, "Wait for generation or cancel it before changing this thread"
                )
            if "head_id" in body.model_fields_set and body.head_id:
                await branch_messages(session, thread, body.head_id)
            for key in body.model_fields_set:
                if key == "status" and body.status is None:
                    raise ApplicationError(422, "Status cannot be null")
                setattr(thread, key, getattr(body, key))
            return thread_dict(thread)

    async def delete(self, thread_id, principal):
        async with self.sessions.begin() as session:
            await owned_thread(session, thread_id, principal, lock=True)
            if await session.scalar(
                select(GenerationRun.id).where(
                    GenerationRun.thread_id == thread_id, GenerationRun.status.in_(ACTIVE)
                )
            ):
                raise ApplicationError(409, "Cancel generation before deleting")
            await session.execute(delete(Thread).where(Thread.id == thread_id))

    async def history(self, thread_id, principal, head_id=None, limit=100):
        async with self.sessions() as session:
            thread = await owned_thread(session, thread_id, principal)
            messages, older = await branch_messages(session, thread, head_id, limit)
            run = await session.scalar(
                select(GenerationRun).where(
                    GenerationRun.thread_id == thread_id, GenerationRun.status.in_(ACTIVE)
                )
            )
            return {
                "messages": [
                    message_dict(m, await message_sources(session, m.id, principal.companies))
                    for m in messages
                ],
                "older_head_id": older,
                "active_run": run_dict(run) if run else None,
            }

    async def branches(self, thread_id, principal, offset=0):
        async with self.sessions() as session:
            thread = await owned_thread(session, thread_id, principal)
            messages = (
                await session.scalars(
                    select(Message)
                    .where(Message.thread_id == thread_id, Message.role == "assistant")
                    .order_by(Message.created_at.desc(), Message.id)
                    .offset(offset)
                    .limit(101)
                )
            ).all()
            return {
                "head_id": thread.head_id,
                "branches": [
                    {"id": m.id, "preview": m.text[:100], "status": m.status}
                    for m in messages[:100]
                ],
                "next_offset": offset + 100 if len(messages) > 100 else None,
            }
