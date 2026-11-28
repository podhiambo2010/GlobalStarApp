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
import sys
from urllib.parse import quote

from supabase_compare_v1_readonly import read_remote_state, POOLER_HOST, PROJECT_REF, EXPECTED_ROLE

HERE = Path(__file__).resolve().parent
TARGET = HERE / ".streamlit" / "secrets.toml"


def _password_from_window():
    """Masked OS-native entry, supporting mouse paste and Ctrl+V."""
    import tkinter as tk
    from tkinter import simpledialog

    window = tk.Tk()
    window.withdraw()
    try:
        window.attributes("-topmost", True)
        password = simpledialog.askstring(
            "GlobalStarApp restricted database",
            "Paste your SAVED database password here (masked), then click OK:",
            show="*", parent=window,
        )
        return password or ""
    finally:
        window.destroy()


def _safe_error_label(exc):
    """Do not print driver errors that might contain connection identifiers."""
    message = str(exc).lower()
    if "password authentication failed" in message or "authentication failed" in message:
        return "Database rejected the password or login. Verify the saved password."
    if "could not translate host name" in message or "name resolution" in message:
        return "Cannot resolve the Supabase database host; check Internet/DNS."
    if "timeout" in message or "timed out" in message:
        return "Connection timed out; check Internet or firewall connectivity."
    if "permission denied" in message or "insufficientprivilege" in message:
        return "Database permissions rejected the read-only query."
    return f"Database connection failed ({exc.__class__.__name__}); no secret was saved."


def setup(gui=False):
    if TARGET.exists():
        print("Existing private secrets file detected. No overwrite attempted.")
        return 0
    secret = _password_from_window() if gui else getpass(
        "Enter the saved restricted Streamlit database password: "
    )
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
        print(_safe_error_label(exc))
        print("No secret file was created. No financial records were changed.")
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
    raise SystemExit(setup(gui="--gui" in sys.argv[1:]))
