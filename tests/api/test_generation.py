from pathlib import Path


def test_end_to_end_generation_creates_pdf_files(submit_job, make_recipients, output_dir):
    job_id, status = submit_job(make_recipients(3))

    assert status["status"] == "completed"
    files = sorted((output_dir / job_id).glob("*.pdf"))
    assert len(files) == 3
    for f in files:
        assert f.read_bytes().startswith(b"%PDF-")


def test_each_certificate_gets_its_own_file(submit_job, make_recipients, fetch_job):
    job_id, _ = submit_job(make_recipients(3))
    paths = [c.file_path for c in fetch_job(job_id).certificates]
    assert len(set(paths)) == 3
    assert all(Path(p).exists() for p in paths)


def test_bulk_request_in_a_single_call(submit_job, make_recipients):
    _, status = submit_job(make_recipients(60))

    assert status["status"] == "completed"
    assert status["total"] == 60
    assert status["succeeded"] == 60
    assert status["progress_percent"] == 100.0
    assert len({c["id"] for c in status["certificates"]}) == 60


def test_duplicate_recipients_get_separate_certificates(submit_job):
    same = {"name": "Asha", "email": "a@example.com"}
    _, status = submit_job([same, same])
    assert status["succeeded"] == 2
    assert status["certificates"][0]["id"] != status["certificates"][1]["id"]


def test_files_of_different_jobs_do_not_mix(submit_job, make_recipients, output_dir):
    id_a, _ = submit_job(make_recipients(2))
    id_b, _ = submit_job(make_recipients(3))
    assert len(list((output_dir / id_a).glob("*.pdf"))) == 2
    assert len(list((output_dir / id_b).glob("*.pdf"))) == 3


def test_certificate_text_with_latin_accents_works(submit_job):
    _, status = submit_job([{"name": "José Müller-Ñandú", "email": "j@example.com"}])
    assert status["status"] == "completed"


def test_course_info_is_used_for_every_certificate(submit_job, fetch_job, make_recipients):
    job_id, _ = submit_job(make_recipients(2), course_name="Data Science", issued_by="Beta Institute")
    job = fetch_job(job_id)
    assert (job.course_name, job.issued_by) == ("Data Science", "Beta Institute")