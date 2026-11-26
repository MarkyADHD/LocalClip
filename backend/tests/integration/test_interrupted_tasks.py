import pytest
from sqlalchemy import text

from src.repositories.task_repository import TaskRepository
from src.workers.tasks import mark_interrupted_tasks
from tests.integration.test_clip_edit_atomicity import make_task


@pytest.mark.asyncio
async def test_runs_cut_off_by_closing_the_app_can_be_resumed(db_session, tmp_path):
    generation, _, _ = await make_task(db_session, tmp_path, status="processing")
    search, _, _ = await make_task(db_session, tmp_path, status="processing")
    finished, _, _ = await make_task(db_session, tmp_path, status="completed")
    await TaskRepository.save_source_metadata(db_session, search, {"find_more": True})
    await db_session.commit()

    await mark_interrupted_tasks({})

    rows = dict((await db_session.execute(text(
        "SELECT id, status || ' ' || COALESCE(progress_message, '') || ' ' || COALESCE(source_metadata->>'find_more', '-')"
        " FROM tasks WHERE id IN (:a, :b, :c)"
    ), {"a": generation, "b": search, "c": finished})).all())
    assert rows[generation] == "error LocalClip was closed before this finished. false"
    assert rows[search].startswith("completed LocalClip was closed before this finished. Press Find more")
    assert rows[search].endswith("false")
    assert rows[finished] == "completed  -"
