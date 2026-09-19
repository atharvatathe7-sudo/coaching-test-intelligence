from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


from backend.app.database.connection import engine
from sqlalchemy import inspect


def test_database_tables_exist():

    inspector = inspect(engine)

    tables = set(inspector.get_table_names())

    expected = {
        "institutes",
        "batches",
        "students",
        "tests",
        "chapters",
        "topics",
        "questions",
        "student_answers",
        "test_results",
    }

    assert expected.issubset(tables)
