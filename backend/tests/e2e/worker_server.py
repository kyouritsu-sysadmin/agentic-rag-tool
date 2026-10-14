"""Independent mock worker process for browser acceptance; never contacts models."""

import asyncio
from unittest.mock import patch
from kyoritsu_backend.db.session import create_database
from kyoritsu_backend.providers.models import ModelProvider
from kyoritsu_backend.workers.ingest import worker_loop
from tests.e2e.browser_server import settings


async def main():
    with (
        patch(
            "httpx.AsyncHTTPTransport.handle_async_request",
            side_effect=AssertionError("External HTTP forbidden"),
        ),
        patch(
            "httpx.HTTPTransport.handle_request",
            side_effect=AssertionError("External HTTP forbidden"),
        ),
    ):
        engine, sessions = create_database(settings.database_url.get_secret_value())
        models = ModelProvider(settings)
        try:
            await worker_loop(sessions, models, settings)
        finally:
            await models.close()
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
