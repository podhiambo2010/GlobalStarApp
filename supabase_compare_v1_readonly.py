"""Section 02: restricted, read-only Supabase comparison for gs_streamlit_v1.

No import, mutation, approval, or ledger posting is implemented here.
A dedicated PostgreSQL LOGIN member of gs_streamlit_v1_reader is required.
"""
from __future__ import annotations

from collections import Counter
import os

SCHEMA = "gs_streamlit_v1"
EXPECTED_ROLE = "gs_streamlit_v1_login"
PROJECT_REF = "ububmwidtfcrdzycgqdf"
POOLER_HOST = "aws-0-eu-central-1.pooler.supabase.com"
DIRECT_HOST = f"db.{PROJECT_REF}.supabase.co"
TABLES = (
    "tenancies", "opening_rent_balances", "deposit_accounts",
    "import_batches", "bank_movements", "batch_movements",
    "allocation_reviews", "audit_events",
)


def compare_summary(manifest, remote_counts, remote_fingerprints=()):
    """Pure comparison: no calls to a database and no changes to evidence."""
    if manifest.get("schema") != SCHEMA or manifest.get("mode") != "DRY_RUN_ONLY_NO_DB_WRITES":
        raise ValueError("Expected approved local Stage 1D dry-run manifest")
    movements = manifest.get("bank_movements", [])
    if not isinstance(movements, list):
        raise ValueError("Invalid local bank movement inventory")
    local_fingerprints = [str(row["fingerprint"]) for row in movements]
    duplicate_local_fingerprints = sorted(
        fingerprint for fingerprint, count in Counter(local_fingerprints).items()
        if count > 1
    )
    remote = set(str(value).strip() for value in remote_fingerprints)
    overlapping = sum(fingerprint in remote for fingerprint in local_fingerprints)
    return {
        "mode": "READ_ONLY_COMPARISON_NO_IMPORT",
        "schema": SCHEMA,
        "local_tenancies": len(manifest.get("tenancies", [])),
        "local_bank_rows": len(movements),
        "local_duplicate_fingerprint_groups": len(duplicate_local_fingerprints),
        "remote_counts": {name: int(remote_counts[name]) for name in TABLES},
        "bank_fingerprint_matches": overlapping,
        "unmatched_local_bank_rows": len(movements) - overlapping,
        "requires_review": bool(duplicate_local_fingerprints),
        "note": "Fingerprint matches are comparisons only, never permission to deduplicate bank rows.",
    }


def read_remote_state(dsn=None):
    """Only SELECT statements, with an explicitly READ ONLY database transaction."""
    dsn = dsn or os.environ.get("GS_V1_READONLY_DSN", "")
    if not dsn:
        raise ValueError("GS_V1_READONLY_DSN is not configured (no database connection attempted)")
    try:
        import psycopg2
    except ImportError as exc:
        raise RuntimeError("Install psycopg2-binary from requirements.txt") from exc
    params = psycopg2.extensions.parse_dsn(dsn)
    host = params.get("host", "")
    username = params.get("user", "")
    if not ((host == POOLER_HOST and username == f"{EXPECTED_ROLE}.{PROJECT_REF}")
            or (host == DIRECT_HOST and username == EXPECTED_ROLE)):
        raise PermissionError("Only the dedicated GlobalStar Streamlit database endpoint and login are allowed")
    counts = {}
    fingerprints = []
    # TLS-encrypted connection with bounded timeouts; no data mutation.
    with psycopg2.connect(
        dsn=dsn, sslmode="require", connect_timeout=8,
        options="-c statement_timeout=8000",
    ) as conn:
        conn.set_session(readonly=True, autocommit=False)
        with conn.cursor() as cur:
            cur.execute("SELECT current_user, current_database()")
            role, db = cur.fetchone()
            if role != EXPECTED_ROLE or db != "postgres":
                raise PermissionError("Unexpected database identity; comparison blocked")
            for table in TABLES:
                cur.execute(f'SELECT count(*) FROM "{SCHEMA}"."{table}"')
                counts[table] = int(cur.fetchone()[0])
            cur.execute(f'SELECT movement_fingerprint FROM "{SCHEMA}"."bank_movements"')
            fingerprints = [str(row[0]).strip() for row in cur.fetchall()]
    return counts, fingerprints
