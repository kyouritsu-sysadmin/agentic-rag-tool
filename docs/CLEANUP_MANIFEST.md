# Handover cleanup manifest

Archived and checksum-verified before removal on 2026-10-14. No database or database volume was changed.

Private recovery archive: `archives/pre-handoff-2026-10-14.tar.gz` (excluded from Git and the handover package). Detailed file hashes are inside its `ARCHIVE_MANIFEST.json`.

Archive SHA-256: `67b4d3dea394351f96d3241f3abb44bf59eeb5da0909229e6e5e6a51fef8965e`.

## Removed from active layout

- `api`: 21 files, 1067688 bytes archived.
- `retrieval`: 11 files, 157841 bytes archived.
- `ingestion`: 3 files, 9366 bytes archived.
- `chunking`: 6 files, 77417 bytes archived.
- `embedding`: 4 files, 31284 bytes archived.
- `evaluation`: 3 files, 39105 bytes archived.
- `config`: 8 files, 55745 bytes archived.
- `data`: 74 files, 4643607 bytes archived.
- `dataset`: 4 files, 5986545 bytes archived.
- `eval`: 144 files, 4827676 bytes archived.
- `logs`: 17 files, 2505596 bytes archived.
- `tests`: 4 files, 5935891 bytes archived.
- `.deepeval`: 4 files, 491989 bytes archived.
- `test-results`: 1 files, 58978 bytes archived.
- `agent_play.py`: 1 files, 2317 bytes archived.
- `PROGRESS.md`: 1 files, 3673 bytes archived.
- `task.progress.md`: 1 files, 9421 bytes archived.
- `RAG 1 Data ingestion.txt`: 1 files, 191 bytes archived.
- `Untitled Diagram - draw.io.html`: 1 files, 598532 bytes archived.
- `sql.txt`: 1 files, 1218 bytes archived.
- `postgresql/docker-compose.yaml.bak-2026-09-24`: 1 files, 897 bytes archived.
- `frontend/src/app/api`: 4 files, 1064 bytes archived.

## Preserved

- Application source, migrations, tests, lockfiles and CI remain maintained.
- Summary generation is now in `backend/src/kyoritsu_backend/providers/summaries.py`.
- Keyword generation is preserved in `backend/scripts/build_keywords.py`; output matched all 122 legacy entries.
- Historical evaluation algorithms and private corpora remain recoverable in the private archive; the maintained evaluation CLI reports retrieval metrics only.
- Original PostgreSQL Compose configuration and private environment remain at their existing paths.
- `.venv/`, frontend dependencies/builds, current environment files, runtime source storage and the thermal watchdog remain local and are excluded from handover packaging.
- No Git history rewrite, application database migration or volume deletion was performed. The maintained source/retirements are recorded in the handover commit; the pre-existing PostgreSQL modification remains separate.
