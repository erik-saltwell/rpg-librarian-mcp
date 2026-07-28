from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run_command(
    command: list[str],
    *,
    env: dict[str, str],
) -> None:
    """Run a command and fail if it returns a nonzero exit code."""
    print(f"> {' '.join(command)}")
    subprocess.run(
        command,
        env=env,
        check=True,
    )


def main() -> int:
    """Verify that checked-in migrations match SQLModel metadata."""
    with tempfile.TemporaryDirectory(
        prefix="alembic-check-",
    ) as temporary_directory:
        database_path = Path(temporary_directory).resolve() / "migration-check.db"

        # Four slashes are needed for an absolute Unix SQLite path.
        # Path.as_posix() also gives SQLite a suitable path on Windows.
        database_url = f"sqlite:///{database_path.as_posix()}"

        environment = os.environ.copy()
        environment["DATABASE_URL"] = database_url

        try:
            # Build a fresh database using only migration files.
            alembic_ini = "src/rpg_librarian_mcp/alembic/alembic.ini"

            run_command(
                [
                    "uv",
                    "run",
                    "alembic",
                    "-c",
                    alembic_ini,
                    "upgrade",
                    "head",
                ],
                env=environment,
            )

            # Compare that migrated database with SQLModel.metadata.
            run_command(
                [
                    "uv",
                    "run",
                    "alembic",
                    "-c",
                    alembic_ini,
                    "check",
                ],
                env=environment,
            )
        except subprocess.CalledProcessError as error:
            print(
                "\nMigration check failed.\n"
                "Your SQLModel tables may differ from the schema "
                "produced by the checked-in migrations.",
                file=sys.stderr,
            )
            return error.returncode

    print("\nMigrations match the SQLModel schema.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
