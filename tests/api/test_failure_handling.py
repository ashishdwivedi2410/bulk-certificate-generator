from app.services import generator_service


def patch_generator(monkeypatch, fail_for, exc=RuntimeError("generation exploded")):
    """Make the generator raise for the named recipients, work normally otherwise."""
    real = generator_service.generate_certificate

    def flaky(**kwargs):
        if kwargs["recipient_name"] in fail_for:
            raise exc
        return real(**kwargs)

    monkeypatch.setattr(generator_service, "generate_certificate", flaky)


def test_one_failing_certificate_does_not_stop_the_rest(submit_job, make_recipients, monkeypatch):
    patch_generator(monkeypatch, {"Student 2"})
    _, status = submit_job(make_recipients(4))

    assert status["status"] == "completed_with_errors"
    assert (status["total"], status["succeeded"], status["failed"]) == (4, 3, 1)
    assert [c["status"] for c in status["certificates"]] == ["success", "failed", "success", "success"]


def test_failure_details_identify_the_recipient(submit_job, make_recipients, monkeypatch):
    patch_generator(monkeypatch, {"Student 2"})
    _, status = submit_job(make_recipients(3))

    failed = [c for c in status["certificates"] if c["status"] == "failed"]
    assert len(failed) == 1
    assert failed[0]["recipient_name"] == "Student 2"
    assert failed[0]["recipient_email"] == "student2@example.com"
    assert failed[0]["row_index"] == 1
    assert failed[0]["error_message"] == "generation exploded"
    assert failed[0]["download_url"] is None


def test_failed_certificate_is_not_downloadable_but_others_are(
    client, submit_job, make_recipients, monkeypatch
):
    patch_generator(monkeypatch, {"Student 1"})
    _, status = submit_job(make_recipients(2))
    failed, ok = status["certificates"]

    assert client.get(f"/certificates/{failed['id']}/download").status_code == 409
    assert client.get(ok["download_url"]).status_code == 200


def test_other_exception_types_are_also_isolated(submit_job, make_recipients, monkeypatch):
    patch_generator(monkeypatch, {"Student 1"}, exc=OSError("disk full"))
    _, status = submit_job(make_recipients(2))
    assert (status["succeeded"], status["failed"]) == (1, 1)


def test_all_certificates_failing_marks_job_failed(submit_job, make_recipients, monkeypatch):
    patch_generator(monkeypatch, {"Student 1", "Student 2", "Student 3"})
    _, status = submit_job(make_recipients(3))

    assert status["status"] == "failed"
    assert (status["succeeded"], status["failed"]) == (0, 3)
    assert status["progress_percent"] == 100.0


def test_real_rendering_failure_without_mocking(submit_job, make_recipients):
    # Valid input that the PDF font cannot render
    recipients = [make_recipients(1)[0], {"name": "राहुल", "email": "r@example.com"}]
    _, status = submit_job(recipients)

    assert status["status"] == "completed_with_errors"
    assert status["certificates"][0]["status"] == "success"
    assert status["certificates"][1]["status"] == "failed"
    assert "cannot render" in status["certificates"][1]["error_message"]


def test_validation_failures_and_generation_failures_are_counted_together(
    submit_job, make_recipients, monkeypatch
):
    patch_generator(monkeypatch, {"Student 2"})
    good = make_recipients(3)
    _, status = submit_job([good[0], {"name": "Bad", "email": "nope"}, good[1], good[2]])

    assert status["total"] == 4
    assert status["succeeded"] == 2
    assert status["failed"] == 2  # one invalid row + one generation failure
    assert status["succeeded"] + status["failed"] == status["total"]
    assert [c["status"] for c in status["certificates"]] == ["success", "failed", "failed", "success"]


def test_failure_leaves_no_partial_files(submit_job, make_recipients, output_dir):
    job_id, _ = submit_job([{"name": "राहुल", "email": "r@example.com"}, *make_recipients(1)])
    names = [p.name for p in (output_dir / job_id).iterdir()]
    assert len(names) == 1 and names[0].endswith(".pdf")  # no .tmp leftovers