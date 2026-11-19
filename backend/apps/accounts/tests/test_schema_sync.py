import io
from pathlib import Path

from django.core.management import call_command


def test_committed_schema_matches_spectacular():
    """Verify that committed schema.yml matches manage.py spectacular output."""
    repo_root = Path(__file__).resolve().parent.parent.parent.parent.parent
    schema_path = repo_root / "schema.yml"
    assert schema_path.exists(), "schema.yml must exist at repo root"

    out = io.StringIO()
    call_command("spectacular", stdout=out)
    generated_schema = out.getvalue()
    committed_schema = schema_path.read_text()

    from django.db import connection

    gen_text = generated_schema.strip()
    comm_text = committed_schema.strip()

    if connection.vendor == "sqlite":
        # Normalize DB-specific positive integer limits (SQLite defaults to int64, PostgreSQL to 32-bit int)
        gen_text = gen_text.replace(
            "maximum: 9223372036854775807\n          minimum: 0\n          format: int64",
            "maximum: 2147483647\n          minimum: 0",
        )

    assert comm_text == gen_text, (
        "Committed schema.yml is out of sync with backend code. "
        "Run: python backend/manage.py spectacular --file schema.yml"
    )
