import time

import pytest

from ai_teacher_api.common import workspace
from ai_teacher_api.teacher import jobs


def wait(job):
    for _ in range(100):
        if job["status"] != "running":
            return
        time.sleep(0.05)


def test_job_runs_reports_stage_and_releases_the_image_lock():
    job = jobs.start("t", "label", lambda progress: (progress("stage one"), {"x": 1})[1])
    wait(job)
    assert job["status"] == "done" and job["stage"] == "stage one" and job["result"] == {"x": 1}
    assert workspace.try_acquire("after")
    workspace.release()


def test_failed_job_records_error_and_releases():
    def boom(progress):
        raise ValueError("bad")

    job = jobs.start("t", "label", boom)
    wait(job)
    assert job["status"] == "failed" and "bad" in job["error"]
    assert workspace.try_acquire("after")
    workspace.release()


def test_second_image_job_is_refused_while_busy():
    assert workspace.try_acquire("someone")
    try:
        with pytest.raises(RuntimeError):
            jobs.start("t", "x", lambda p: {})
    finally:
        workspace.release()
