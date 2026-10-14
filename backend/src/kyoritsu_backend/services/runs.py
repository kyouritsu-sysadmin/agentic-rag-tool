from kyoritsu_backend.db.models import Message
from kyoritsu_backend.db.repositories import owned_run, message_sources
from kyoritsu_backend.schemas.serialization import run_dict, message_dict


class RunService:
    def __init__(self, sessions, chat):
        self.sessions, self.chat = sessions, chat

    async def get(self, run_id, principal):
        async with self.sessions() as session:
            run = await owned_run(session, run_id, principal)
            return {
                **run_dict(run),
                "message": message_dict(
                    await session.get(Message, run.assistant_message_id),
                    await message_sources(session, run.assistant_message_id, principal.companies),
                ),
            }

    async def cancel(self, run_id, principal):
        async with self.sessions() as session:
            await owned_run(session, run_id, principal)
        await self.chat.cancel(run_id)
        return await self.get(run_id, principal)

    async def authorize(self, run_id, principal):
        async with self.sessions() as session:
            await owned_run(session, run_id, principal)
