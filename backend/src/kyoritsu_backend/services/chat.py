import asyncio
import hashlib
import json
import logging
import time
import re
from pydantic_core import to_jsonable_python
from kyoritsu_backend.core.errors import ApplicationError
from sqlalchemy import select
from kyoritsu_backend.rag.conversation import contextual_request
from kyoritsu_backend.db.models import Thread, Message, GenerationRun, MessageSource, now
from kyoritsu_backend.db.repositories import owned_thread, branch_messages
from kyoritsu_backend.providers.answers import answer

logger = logging.getLogger(__name__)
ACTIVE = {"queued", "running"}


class ChatService:
    def __init__(self, sessions, retrieval, settings):
        self.sessions, self.retrieval, self.settings = sessions, retrieval, settings
        self.tasks = {}
        self.admission = asyncio.Lock()

    async def submit(self, thread_id, request, principal):
        async with self.admission:
            return await self._submit(thread_id, request, principal)

    async def _submit(self, thread_id, request, principal):
        fingerprint = hashlib.sha256(
            json.dumps(request.model_dump(exclude_unset=True), sort_keys=True).encode()
        ).hexdigest()
        async with self.sessions.begin() as session:
            thread = await owned_thread(session, thread_id, principal, lock=True)
            existing = await session.scalar(
                select(GenerationRun).where(
                    GenerationRun.thread_id == thread_id,
                    GenerationRun.idempotency_key == request.idempotency_key,
                )
            )
            if existing:
                if existing.request_hash != fingerprint:
                    raise ApplicationError(409, "Idempotency key has a different request")
                return existing
            if len(self.tasks) >= self.settings.max_active_runs:
                raise ApplicationError(503, "Generation capacity is full; retry later")
            if thread.status == "archived":
                raise ApplicationError(409, "Unarchive this thread before sending")
            if await session.scalar(
                select(GenerationRun.id).where(
                    GenerationRun.thread_id == thread_id, GenerationRun.status.in_(ACTIVE)
                )
            ):
                raise ApplicationError(409, "A generation is already active in this thread")
            if request.model_id != "default":
                raise ApplicationError(422, "Unknown model")
            # Omitted parent appends to current branch; explicit null creates a new root.
            parent_id = (
                request.parent_id if "parent_id" in request.model_fields_set else thread.head_id
            )
            if parent_id:
                parent = await session.get(Message, parent_id)
                if not parent or parent.thread_id != thread_id:
                    raise ApplicationError(404, "Parent message not found")
                if parent.role != "assistant":
                    raise ApplicationError(
                        422, "A new user message must follow an assistant message"
                    )
            previous = None
            history = []
            if parent_id:
                parent_run = await session.scalar(
                    select(GenerationRun).where(GenerationRun.assistant_message_id == parent_id)
                )
                previous = parent_run.configuration.get("retrieval_request") if parent_run else None
                if not previous:
                    # Compatibility for branches created before context was persisted.
                    head = parent_id
                    while head:
                        page, head = await branch_messages(session, thread, head, max_count=200)
                        history = [{"role": m.role, "content": m.text} for m in page] + history
            history.append({"role": "user", "content": request.text})
            resolved = contextual_request(
                history, no_rerank=not self.settings.enable_rerank, previous=previous
            )
            user = Message(thread_id=thread_id, parent_id=parent_id, role="user", text=request.text)
            session.add(user)
            await session.flush()
            assistant = Message(
                thread_id=thread_id, parent_id=user.id, role="assistant", status="queued"
            )
            session.add(assistant)
            await session.flush()
            run = GenerationRun(
                thread_id=thread_id,
                user_message_id=user.id,
                assistant_message_id=assistant.id,
                idempotency_key=request.idempotency_key,
                request_hash=fingerprint,
                model_id=request.model_id,
                configuration={
                    "answer_model": self.settings.answer_model,
                    "companies": list(principal.companies),
                    "retrieval_request": resolved.model_dump(mode="json"),
                },
            )
            session.add(run)
            thread.head_id = assistant.id
            thread.title = thread.title or request.text[:80]
            await session.flush()
        self.tasks[run.id] = asyncio.create_task(self.generate(run.id, principal))
        self.tasks[run.id].add_done_callback(lambda _: self.tasks.pop(run.id, None))
        return run

    async def persist(self, run_id, content, status, error=None):
        async with self.sessions.begin() as session:
            run = await session.get(GenerationRun, run_id, with_for_update=True)
            if not run or run.status not in ACTIVE:
                return False
            run.status, run.error, run.updated_at = status, error, now()
            message = await session.get(Message, run.assistant_message_id)
            message.text, message.status = content, status
        return True

    async def generate(self, run_id, principal):
        content = ""
        try:
            async with asyncio.timeout(self.settings.generation_timeout):
                async with self.sessions() as session:
                    run = await session.get(GenerationRun, run_id)
                    thread = await session.get(Thread, run.thread_id)
                    messages, _ = await branch_messages(
                        session, thread, run.user_message_id, max_count=12
                    )
                    history = [
                        {"role": m.role, "content": m.text}
                        for m in messages
                        if m.role == "user" or m.status == "completed"
                    ]
                if not await self.persist(run_id, content, "running"):
                    return
                evidence = await self.retrieval.retrieve(
                    contextual_request([], previous=run.configuration["retrieval_request"]),
                    principal,
                )
                async with self.sessions.begin() as session:
                    current = await session.get(GenerationRun, run_id, with_for_update=True)
                    if not current or current.status not in ACTIVE:
                        return
                    current.configuration = to_jsonable_python(
                        {
                            **current.configuration,
                            "retrieval": {
                                "scopes": evidence["scopes"],
                                "coverage": evidence["coverage"],
                            },
                        }
                    )
                    for i, c in enumerate(evidence["chunks"], 1):
                        session.add(
                            MessageSource(
                                message_id=run.assistant_message_id,
                                chunk_id=c["doc_chunk_id"],
                                position=i,
                                score=c["rrf_score"],
                            )
                        )
                last_save = time.monotonic()
                async for token in answer(self.settings, history, evidence):
                    content += token
                    if time.monotonic() - last_save >= 0.2:
                        if not await self.persist(run_id, content, "running"):
                            return
                        last_save = time.monotonic()
                references = [int(number) for number in re.findall(r"\[(\d+)\]", content)]
                if any(number < 1 or number > len(evidence["chunks"]) for number in references):
                    raise ValueError("Answer cited an unknown source")
                if evidence["chunks"] and not references:
                    raise ValueError("Answer did not cite supporting evidence")
                await self.persist(run_id, content, "completed")
        except asyncio.CancelledError:
            await self.persist(run_id, content, "cancelled")
        except TimeoutError:
            await self.persist(run_id, content, "failed", "Generation timed out")
        except Exception:
            logger.exception("Generation failed: run=%s", run_id)
            await self.persist(
                run_id, content, "failed", "Generation failed; inspect server logs using run ID"
            )

    async def cancel(self, run_id):
        task = self.tasks.get(run_id)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        # Also handles a task cancelled before its coroutine starts.
        async with self.sessions.begin() as session:
            run = await session.get(GenerationRun, run_id, with_for_update=True)
            if run and run.status in ACTIVE:
                run.status, run.updated_at = "cancelled", now()
                (await session.get(Message, run.assistant_message_id)).status = "cancelled"

    async def close(self):
        await asyncio.gather(
            *(self.cancel(key) for key in list(self.tasks)), return_exceptions=True
        )
