# Legacy disposition

Legacy implementations, private documents/evaluation data, logs, SQL drafts, retired frontend API routes and stale notes were archived and checksum-verified before removal from the active layout. See [CLEANUP_MANIFEST.md](CLEANUP_MANIFEST.md) for the exact disposition.

The private recovery archive is ignored by Git and excluded from handover packaging. Do not restore its contents into the active runtime without review. Summary generation and deterministic keyword generation have maintained replacements; historical evaluation code/data remain recoverable in the archive. Database volumes, local PostgreSQL configuration, current environment files and the thermal watchdog remain preserved.
