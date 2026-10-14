"""Supported query/evaluation clients use the authoritative FastAPI service."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import httpx
from sqlalchemy import text
from kyoritsu_backend.core.settings import Settings
from kyoritsu_backend.db.session import create_database


async def execute(args):
    if args.command == "inspect-db":
        settings = Settings()
        engine, _ = create_database(settings.database_url.get_secret_value())
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SET TRANSACTION READ ONLY"))
                tables = (
                    (
                        await conn.execute(
                            text(
                                "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name"
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                columns = (
                    (
                        await conn.execute(
                            text(
                                "SELECT table_name,column_name,data_type,is_nullable FROM information_schema.columns WHERE table_schema='public' ORDER BY table_name,ordinal_position"
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                extensions = (
                    (
                        await conn.execute(
                            text("SELECT extname,extversion FROM pg_extension ORDER BY extname")
                        )
                    )
                    .mappings()
                    .all()
                )
                counts = {}
                for name in tables:
                    quoted = conn.dialect.identifier_preparer.quote(name)
                    counts[name] = await conn.scalar(text(f"SELECT count(*) FROM public.{quoted}"))
                print(
                    json.dumps(
                        {
                            "tables": counts,
                            "columns": [dict(c) for c in columns],
                            "extensions": [dict(e) for e in extensions],
                        },
                        indent=2,
                    )
                )
        finally:
            await engine.dispose()
        return
    token = os.environ.get("RAG_ACCESS_TOKEN")
    if not token:
        raise SystemExit("Set RAG_ACCESS_TOKEN; tokens are never accepted as command arguments")
    async with httpx.AsyncClient(
        base_url=args.url, headers={"Authorization": f"Bearer {token}"}, timeout=120
    ) as client:
        if args.command == "query":
            response = await client.post(
                "/v1/tool/retrieval", json={"query": args.query, "top_k": args.top_k}
            )
            response.raise_for_status()
            print(json.dumps(response.json(), ensure_ascii=False, indent=2))
        elif args.command == "evaluate":
            cases = json.loads(Path(args.corpus).read_text())
            records = []
            for case in cases:
                response = await client.post("/v1/tool/retrieval", json=case["request"])
                response.raise_for_status()
                result = response.json()
                expected = set(case["expected_chunk_ids"])
                if not expected:
                    raise SystemExit("Each labeled case must contain expected_chunk_ids")
                actual = {c["doc_chunk_id"] for c in result["chunks"]}
                records.append(
                    {
                        "id": case["id"],
                        "recall": len(actual & expected) / len(expected),
                        "precision": len(actual & expected) / max(1, len(actual)),
                        "elapsed_ms": result["elapsed_ms"],
                        "returned_ids": sorted(actual),
                        "coverage": result["coverage"],
                    }
                )
            catalog = (await client.get("/v1/models")).json()
            output = {
                "models": catalog,
                "cases": records,
                "mean_recall": sum(c["recall"] for c in records) / max(1, len(records)),
                "scope": "Retrieval metrics only; no fabricated answer-quality score",
            }
            Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8005")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "inspect-db", help="Read-only schema, extensions and row counts; never stamp or migrate"
    )
    query = sub.add_parser("query")
    query.add_argument("query")
    query.add_argument("--top-k", type=int, default=8)
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("corpus")
    evaluate.add_argument("--output", required=True)
    asyncio.run(execute(parser.parse_args()))
