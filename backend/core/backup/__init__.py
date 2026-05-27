"""Firm-data backup + restore — Phase 5 / Week 23 / Day 4.

Round-trippable archive: every row tied to a firm (sessions,
reports, comments, memberships, versions, library docs, etc.)
exported to a portable JSON file. Restore re-inserts into a
clean instance + verifies integrity.

Pilot insurance: if something corrupts during the pilot, a
recent backup can be restored to a fresh DB and the firm picks
up where it left off.

Out of scope: artifact-file bytes (PPTX/XLSX/PDF). Those live
on disk + S3 — backup is a separate rsync/S3-snapshot
responsibility. The backup archive does carry the
``export_artifacts`` rows (the metadata about which artifacts
existed) so a restore can re-render them from the payload if
the files themselves are gone.
"""

from .archive import (
    BackupArchive,
    BACKUP_VERSION,
    backup_firm,
    restore_firm,
)

__all__ = [
    "BACKUP_VERSION",
    "BackupArchive",
    "backup_firm",
    "restore_firm",
]
