# Sanity checks on the job status enum. Trivial on their own, but they
# catch accidentally renaming/removing a status string that other code
# (raw Mongo queries, API routes) depends on matching exactly.

from shared.db.models.job import JobStatus, new_video_job


def test_all_status_values_are_unique():
    values = [s.value for s in JobStatus]
    assert len(values) == len(set(values))


def test_expected_statuses_exist():
    expected = {
        "pending", "downloading", "downloaded", "processing",
        "transcribed", "failed", "excluded",
    }
    actual = {s.value for s in JobStatus}
    assert expected <= actual


def test_new_video_job_defaults_to_pending():
    job = new_video_job(video_url="https://example.com/1", source="michigan_senate")
    assert job["status"] == JobStatus.PENDING
    assert job["retries"] == 0
    assert job["error"] is None


def test_new_video_job_does_not_share_mutable_default_metadata():
    # Regression guard: metadata=None must not resolve to a single dict
    # shared across every job.
    job_a = new_video_job(video_url="a", source="s")
    job_b = new_video_job(video_url="b", source="s")
    job_a["metadata"]["title"] = "A"
    assert "title" not in job_b["metadata"]
