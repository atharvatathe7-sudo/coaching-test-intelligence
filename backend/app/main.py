from fastapi import FastAPI
from sqlalchemy import text

from .database.connection import Base, engine
from .database import models  # noqa: F401


app = FastAPI(
    title="Coaching Test Intelligence",
    version="0.1.0",
)


# Create database tables when the application starts.
Base.metadata.create_all(bind=engine)


@app.get("/")
def root():
    return {
        "application": "Coaching Test Intelligence",
        "version": "0.1.0",
        "status": "running",
    }


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "database": "connected",
    }


@app.get("/api/database/tables")
def database_tables():
    with engine.connect() as connection:
        result = connection.execute(
            text(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                ORDER BY name
                """
            )
        )

        tables = [row[0] for row in result]

    return {
        "tables": tables,
    }
