from kyoritsu_backend.core.errors import ApplicationError
from sqlalchemy import select
from .models import Thread, Message, GenerationRun, MessageSource, Chunk, DocumentVersion


async def owned_thread(session, thread_id, principal, lock=False):
    stmt = select(Thread).where(Thread.id == thread_id, Thread.owner_id == principal.subject)
    if lock:
        stmt = stmt.with_for_update()
    thread = await session.scalar(stmt)
    if not thread:
        raise ApplicationError(404, "Thread not found")
    return thread


async def owned_run(session, run_id, principal):
    run = await session.get(GenerationRun, run_id)
    if not run:
        raise ApplicationError(404, "Run not found")
    await owned_thread(session, run.thread_id, principal)
    return run


async def message_sources(session, message_id, companies):
    sources = await session.execute(
        select(MessageSource, Chunk, DocumentVersion)
        .join(Chunk, MessageSource.chunk_id == Chunk.doc_chunk_id)
        .join(DocumentVersion, Chunk.version_id == DocumentVersion.id)
        .where(MessageSource.message_id == message_id, Chunk.company.in_(companies))
        .order_by(MessageSource.position)
    )
    return sources.all()


async def branch_messages(session, thread, head_id=None, max_count=200):
    current = head_id if head_id is not None else thread.head_id
    result, seen = [], set()
    while current and len(result) < max_count:
        if current in seen:
            raise ApplicationError(409, "Invalid message ancestry")
        seen.add(current)
        message = await session.get(Message, current)
        if not message or message.thread_id != thread.id:
            raise ApplicationError(404, "Message not found in thread")
        result.append(message)
        current = message.parent_id
    return list(reversed(result)), current
