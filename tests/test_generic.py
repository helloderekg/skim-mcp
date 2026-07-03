"""Generic/data path: retention promotion + dedup, plus airtightness."""
import os
import tempfile

from helpers import assert_airtight
from skim import skim_file


def _skim(src: str, suffix: str):
    fd, p = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(src)
        return skim_file(p)
    finally:
        os.unlink(p)


def test_dedup_collapses_identical_blocks():
    block = "ERROR boom\n  detail x\n  trace y"
    r = _skim(block + "\n\n" + block + "\n", ".log")
    assert "identical to" in r.skeleton


def test_retention_promotes_ip_and_code():
    r = _skim("header line\n  failed at host 10.20.30.40 with code ABC123\n", ".log")
    assert "10.20.30.40" in r.skeleton    # IPv4 surfaced
    assert "ABC123" in r.skeleton         # error code surfaced


def test_generic_single_line_blocks_kept():
    # blocks are blank-line delimited; blank-separated single lines are each kept verbatim
    r = _skim("alpha\n\nbeta\n\ngamma\n", ".log")
    for w in ("alpha", "beta", "gamma"):
        assert w in r.skeleton


def test_skim_text_reconstruction_byte_exact():
    from skim import skim_text
    for s in ("a\nb\nc", "one\fpage\ntwo", "tab\vhere\nend", "", "no newline at all"):
        assert skim_text(s).full_text == s     # exotic separators are content, not line breaks


def test_generic_airtight_variants():
    for src, suf in [("a\nb\n\nc\nd\n", ".log"),
                     ('{"k": [1,2,3], "n": null}\n', ".json"),
                     ("col1,col2\n1,2\n3,4\n", ".csv"),
                     ("no blank lines at all just one block\nsecond\nthird\n", ".txt")]:
        assert_airtight(src, suf)
