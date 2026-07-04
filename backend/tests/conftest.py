import pytest


@pytest.fixture(scope="session", autouse=True)
def _close_db_after_session():
    yield
    from backend.app.db import database
    if database._db_connection is not None:
        import asyncio
        loop = asyncio.new_event_loop()
        loop.run_until_complete(database._db_connection.close())
        loop.close()
        database._db_connection = None
