"""One-time LOCAL setup for GlobalStarApp restricted Supabase reader.

Prompts privately for the existing gs_streamlit_v1_login password. Does not
print it, put it in Git or modify database data. Stores the resulting URI in
.gitignored .streamlit/secrets.toml, as expected by Streamlit.
"""
from __future__ import annotations

from getpass import getpass
from pathlib import Path
import json
import os
from urllib.parse import quote

from supabase_compare_v1_readonly import read_remote_state, POOLER_HOST, PROJECT_REF, EXPECTED_ROLE

HERE = Path(__file__).resolve().parent
TARGET = HERE / ".streamlit" / "secrets.toml"


def setup():
    if TARGET.exists():
        print("Existing private secrets file detected. No overwrite attempted.")
        return 0
    secret = getpass("Enter the saved restricted Streamlit database password: ")
    if not secret:
        print("No password entered. No file created.")
        return 1
    user = quote(f"{EXPECTED_ROLE}.{PROJECT_REF}", safe="")
    password = quote(secret, safe="")
    dsn = f"postgresql://{user}:{password}@{POOLER_HOST}:5432/postgres?sslmode=require"
    del secret, password

    try:
        counts, fingerprints = read_remote_state(dsn=dsn)
    except Exception as exc:
        print(f"Connection verification failed ({exc.__class__.__name__}). No secret saved.")
        return 1

    TARGET.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    body = "# GlobalStarApp local-only restricted read-only connection. DO NOT COMMIT.\n"
    body += "GS_V1_READONLY_DSN = " + json.dumps(dsn) + "\n"
    # Exclusive creation avoids overwriting another local configuration.
    try:
        with TARGET.open("x", encoding="utf-8") as handle:
            handle.write(body)
    except FileExistsError:
        print("Private configuration already exists; it was not overwritten.")
        return 1
    try:
        os.chmod(TARGET, 0o600)
    except OSError:
        print("Warning: Windows ACL should be checked for this local secrets file.")
    print("Private Streamlit connection saved locally (file contents not shown).")
    print("Database SELECT test succeeded for", len(counts), "tables;",
          "bank fingerprints:", len(fingerprints))
    print("From now on, start Streamlit normally: streamlit run app_frontend.py --server.port 8502")
    return 0


if __name__ == "__main__":
    raise SystemExit(setup())
