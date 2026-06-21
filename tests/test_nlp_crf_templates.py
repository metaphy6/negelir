from pathlib import Path


def test_nlp_crf_template_files_exist() -> None:
    base = Path(__file__).resolve().parent.parent / "nlp" / "lang_tr" / "crf_templates"
    expected = ["date.tmpl", "time.tmpl", "score.tmpl", "weekday.tmpl"]
    for name in expected:
        path = base / name
        assert path.is_file(), f"Missing CRF feature template file: {path}"
