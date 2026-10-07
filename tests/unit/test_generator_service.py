import json
from datetime import date

import pytest

from app.core.config import settings
from app.services import generator_service
from app.services.generator_service import GenerationError, generate_certificate


@pytest.fixture
def out(tmp_path):
    folder = tmp_path / "pdfs"
    folder.mkdir()
    return folder


def render(path, name="Asha Verma", course="Python 101"):
    return generate_certificate(
        recipient_name=name,
        course_name=course,
        issued_by="Acme Academy",
        issue_date=date(2026, 10, 1),
        output_path=path,
    )


def test_creates_a_valid_pdf(tmp_path):
    out = render(tmp_path / "a.pdf")
    assert out.exists()
    data = out.read_bytes()
    assert data.startswith(b"%PDF-")
    assert len(data) > 500


def test_creates_missing_parent_folders(tmp_path):
    out = render(tmp_path / "deep" / "er" / "a.pdf")
    assert out.exists()


def test_no_temp_file_left_behind_on_success(out):
    render(out / "a.pdf")
    assert [p.name for p in out.iterdir()] == ["a.pdf"]


def test_different_recipients_give_different_files(tmp_path):
    a = render(tmp_path / "a.pdf", name="Asha").read_bytes()
    b = render(tmp_path / "b.pdf", name="Bhavna").read_bytes()
    assert a != b


def test_long_course_name_is_accepted(tmp_path):
    assert render(tmp_path / "a.pdf", course="Advanced Topics " * 12).exists()


def test_long_but_fitting_name_is_shrunk_not_rejected(tmp_path):
    assert render(tmp_path / "a.pdf", name="Maximilian " * 5).exists()


def test_unrenderable_characters_raise_and_leave_no_file(out):
    with pytest.raises(GenerationError, match="cannot render"):
        render(out / "a.pdf", name="राहुल")
    assert list(out.iterdir()) == []


def test_name_that_cannot_fit_raises(out):
    with pytest.raises(GenerationError, match="too long"):
        render(out / "a.pdf", name="W" * 100)
    assert list(out.iterdir()) == []


def test_unrenderable_course_name_raises(tmp_path):
    with pytest.raises(GenerationError):
        render(tmp_path / "a.pdf", course="पाइथन")


def test_missing_template_file_raises_generation_error(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "template_dir", tmp_path / "no-templates")
    generator_service.load_template.cache_clear()
    try:
        with pytest.raises(GenerationError, match="template"):
            render(tmp_path / "a.pdf")
    finally:
        monkeypatch.undo()
        generator_service.load_template.cache_clear()


def test_broken_template_json_raises_generation_error(tmp_path, monkeypatch):
    tpl_dir = tmp_path / "tpl"
    tpl_dir.mkdir()
    (tpl_dir / "certificate_template.json").write_text("{ not json")
    monkeypatch.setattr(settings, "template_dir", tpl_dir)
    generator_service.load_template.cache_clear()
    try:
        with pytest.raises(GenerationError, match="template"):
            render(tmp_path / "a.pdf")
    finally:
        monkeypatch.undo()
        generator_service.load_template.cache_clear()


def test_real_template_has_the_expected_keys():
    generator_service.load_template.cache_clear()
    tpl = generator_service.load_template()
    for key in ("title", "intro_text", "completion_text", "date_label",
                "issuer_label", "date_format", "colors"):
        assert key in tpl
    assert {"primary", "text", "name"} <= set(tpl["colors"])
    json.dumps(tpl)  # plain JSON data