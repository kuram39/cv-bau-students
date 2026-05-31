"""Tests for document text extraction — focus on the .md addition."""

from __future__ import annotations

import pytest

from cv_bau_students.extractors.document import extract_text


def test_md_is_extracted_like_text():
    body = "# Anna Nováková\n\n- Python\n- SQL\n".encode()
    out = extract_text(body, "cv.md")
    assert "Anna Nováková" in out
    assert "Python" in out


def test_txt_still_works():
    body = b"plain cv text"
    assert extract_text(body, "cv.txt") == "plain cv text"


def test_unsupported_suffix_raises():
    with pytest.raises(ValueError, match="Unsupported file type"):
        extract_text(b"x", "cv.rtf")
