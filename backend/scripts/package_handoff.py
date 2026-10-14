"""Build a handover archive from Git-tracked working-tree source files.

Explicit roots exclude legacy data, credentials, caches, Git history and local archives.
"""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
ROOTS = (
    "README.md",
    ".gitignore",
    ".python-version",
    "pyproject.toml",
    "uv.lock",
    ".github",
    "backend",
    "frontend",
    "deploy",
    "docs",
)
EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    ".next",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "test-results",
    "playwright-report",
    "storage",
}


def sources():
    from kyoritsu_backend.core.settings import Settings

    config = Path(os.environ.get("RAG_ENV_FILE") or ROOT / "backend/.env").expanduser().resolve()
    # Use the application's path resolution and environment precedence. Fail closed
    # on invalid configuration; never print credentials in packaging diagnostics.
    try:
        if os.environ.get("RAG_ENV_FILE") and not config.is_file():
            raise ValueError("Missing explicit configuration")
        storage = Settings(_env_file=config).storage_dir.resolve()
    except Exception:
        raise RuntimeError("Cannot determine private paths; check backend configuration") from None
    tracked = subprocess.check_output(["git", "ls-files", "--cached", "-z"], cwd=ROOT)
    for name in sorted(set(os.fsdecode(tracked).split("\0")) - {""}):
        relative = Path(name)
        if relative.parts[0] not in ROOTS:
            continue
        file = ROOT / relative
        if (
            not file.is_file()
            or any((ROOT / part).is_symlink() for part in (relative, *relative.parents))
            or EXCLUDED_DIRS.intersection(relative.parts)
        ):
            continue
        resolved = file.resolve()
        if resolved == config or resolved == storage or storage in resolved.parents:
            continue
        if any(part.endswith(".egg-info") for part in relative.parts):
            continue
        if file.name.startswith(".env") and file.name != ".env.example":
            continue
        if file.name.startswith(".coverage") or file.suffix in {
            ".env",
            ".pem",
            ".key",
            ".p12",
            ".pfx",
            ".pyc",
            ".log",
            ".tsbuildinfo",
            ".bak",
        }:
            continue
        yield file, relative.as_posix()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/kyoritsu-rag-handoff.tar.gz")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    files = list(sources())
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        commit = None
    manifest = {
        "base_commit": commit,
        "source": "working tree; hashes are authoritative",
        "files": [],
    }
    with tarfile.open(args.output, "w:gz") as archive:
        for file, name in files:
            data = file.read_bytes()
            manifest["files"].append({"path": name, "sha256": hashlib.sha256(data).hexdigest()})
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o644
            archive.addfile(info, io.BytesIO(data))
        data = (json.dumps(manifest, indent=2) + "\n").encode()
        info = tarfile.TarInfo("HANDOFF_MANIFEST.json")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    with tarfile.open(args.output) as archive:
        for item in manifest["files"]:
            assert (
                hashlib.sha256(archive.extractfile(item["path"]).read()).hexdigest()
                == item["sha256"]
            )
    print(f"Verified {len(files)} source files: {args.output}")
    print("Archive SHA-256:", hashlib.sha256(args.output.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
