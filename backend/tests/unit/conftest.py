from contextlib import asynccontextmanager

import pytest
from unittest.mock import AsyncMock


@pytest.fixture(autouse=True)
def no_auto_blur(monkeypatch):
    """Renders in tests don't look for vapes (that would download the models)."""
    monkeypatch.setenv("AUTO_BLUR", "false")


@pytest.fixture
def isolated_clip_edits(monkeypatch):
    """Keep service unit tests independent of the PostgreSQL edit boundary.

    Real transaction behavior is covered in integration/test_clip_edit_atomicity.py.
    """
    @asynccontextmanager
    async def transaction(_db, _task_id):
        yield

    monkeypatch.setattr(
        "src.repositories.edit_transaction.task_edit_transaction", transaction
    )

    monkeypatch.setattr(
        "src.repositories.task_repository.TaskRepository.load_source_metadata",
        AsyncMock(return_value={}),
    )
