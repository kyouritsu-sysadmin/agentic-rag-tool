import asyncio
import json
import os
from tests.database_safety import disposable_database_url

DSN = os.environ.get("RAG_TEST_DATABASE_URL")
if DSN:
    DSN = disposable_database_url(DSN)
TOKEN = "integration-admin-token-0001"
OTHER = "integration-other-token-0002"


async def upload(client, key="import-0001", content="sales profit result " * 40, **kwargs):
    meta = {"company": "A", "dept": "sales", "year": 2025, "month": 1, "import_key": key, **kwargs}
    r = await client.post(
        "/v1/documents",
        data={"metadata": json.dumps(meta)},
        files={"file": ("report.txt", content.encode(), "text/plain")},
    )
    assert r.status_code == 202, r.text
    return r.json()


async def wait_run(client, run_id):
    for _ in range(100):
        result = (await client.get(f"/v1/runs/{run_id}")).json()
        if result["status"] not in {"queued", "running"}:
            return result
        await asyncio.sleep(0.03)
    raise AssertionError("Run did not terminate")
