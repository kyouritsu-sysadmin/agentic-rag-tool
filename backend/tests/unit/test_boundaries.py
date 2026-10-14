"""Keep the handoff's layer boundaries and public API contracts enforceable."""

import ast
from pathlib import Path
from kyoritsu_backend.main import create_app
from kyoritsu_backend.core.settings import Settings

SOURCE = Path(__file__).resolve().parents[2] / "src/kyoritsu_backend"


def imported_modules(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            yield node.module or ""


def test_application_and_database_layers_are_independent_of_http_framework():
    for directory in ["services", "db", "rag", "providers"]:
        for path in (SOURCE / directory).rglob("*.py"):
            assert not any(
                module.split(".")[0] in {"fastapi", "starlette"}
                for module in imported_modules(path)
            ), path


def test_routes_delegate_persistence_and_provider_work():
    for path in (SOURCE / "api/routes").glob("*.py"):
        for module in imported_modules(path):
            assert not module.startswith(
                ("sqlalchemy", "kyoritsu_backend.db", "kyoritsu_backend.providers")
            ), (path, module)


def test_json_endpoints_publish_response_contracts():
    for path, operations in create_app(Settings(_env_file=None)).openapi()["paths"].items():
        if not path.startswith("/v1/") or path.endswith(("/events", "/source")):
            continue
        for method, operation in operations.items():
            for status, response in operation["responses"].items():
                if status.startswith("2") and status != "204":
                    assert "$ref" in response["content"]["application/json"]["schema"], (
                        path,
                        method,
                    )
