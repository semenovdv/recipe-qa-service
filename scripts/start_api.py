"""Bootstrap the database and start the API process.

This keeps a single API image self-starting on Docker platforms that do not
support a separate one-shot seed job. The seeder is idempotent, so repeating
it is safe and preserves the repository as the source of truth.
"""
from __future__ import annotations

import os
import subprocess
import sys


def main() -> None:
    subprocess.run([sys.executable, "-m", "scripts.db_seed", "--apply"], check=True)
    os.execvp(
        "uvicorn",
        ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"],
    )


if __name__ == "__main__":
    main()
