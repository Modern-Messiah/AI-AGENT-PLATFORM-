from __future__ import annotations

from apps.api.services.filenames import safe_upload_filename


def test_strips_path_traversal_and_directories() -> None:
    assert safe_upload_filename("../../etc/passwd") == "passwd"
    assert safe_upload_filename("/abs/path/report.pdf") == "report.pdf"
    assert safe_upload_filename("C:\\Users\\denis\\doc.txt") == "doc.txt"
    assert safe_upload_filename("a/b/c.txt") == "c.txt"


def test_none_and_blank_fall_back_to_unnamed() -> None:
    assert safe_upload_filename(None) == "unnamed"
    assert safe_upload_filename("") == "unnamed"
    assert safe_upload_filename("   ") == "unnamed"
    assert safe_upload_filename("///") == "unnamed"
    assert safe_upload_filename("..") == "unnamed"


def test_control_chars_and_whitespace_replaced() -> None:
    assert safe_upload_filename("bad\x00name.pdf") == "bad_name.pdf"
    assert safe_upload_filename("my report final.pdf") == "my_report_final.pdf"


def test_leading_dots_trimmed() -> None:
    assert safe_upload_filename(".env") == "env"
    assert safe_upload_filename("...secret.txt") == "secret.txt"


def test_long_names_capped_keeping_extension() -> None:
    long_name = "a" * 300 + ".pdf"
    result = safe_upload_filename(long_name)
    assert len(result) == 200
    assert result.endswith(".pdf")

    no_ext = "b" * 300
    assert len(safe_upload_filename(no_ext)) == 200


def test_plain_names_unchanged() -> None:
    assert safe_upload_filename("manual.pdf") == "manual.pdf"
    assert safe_upload_filename("заметки-о-встрече.md") == "заметки-о-встрече.md"
