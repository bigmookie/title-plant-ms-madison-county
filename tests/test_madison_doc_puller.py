"""Tests for madison_doc_puller.py reference parsing, GCS lookup, and web result selection."""

import sys
from pathlib import Path
from unittest import mock

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import madison_doc_puller as mdp  # noqa: E402


# =============================================================================
# Reference parsing
# =============================================================================


@pytest.mark.parametrize(
    "line, book, page, doc_type",
    [
        ("232/392", 232, 392, "deed"),
        ("14-466", 14, 466, "deed"),
        ("DT 502/308", 502, 308, "deed-of-trust"),
        ("dt 338/83", 338, 83, "deed-of-trust"),
        ("DOT 502/308", 502, 308, "deed-of-trust"),
        ("502/308 deed-of-trust", 502, 308, "deed-of-trust"),
        ("502/308 deed of trust", 502, 308, "deed-of-trust"),
        ("500/100 deed book", 500, 100, "deed"),
        ("501-50 plat", 501, 50, "plat"),
        ("CCC/165", "CCC", 165, "deed"),
        ("S/646", "S", 646, "deed"),
        ("ss/52", "SS", 52, "deed"),
        ("M-44", "M", 44, "deed"),
    ],
)
def test_parse_reference_line(line, book, page, doc_type):
    assert mdp.parse_reference_line(line) == {
        "book": book,
        "page": page,
        "doc_type": doc_type,
    }


def test_deed_of_trust_below_book_238_keeps_its_series():
    # Deed of trust books are numbered separately from deed books, so
    # DT 151/206 must not be turned into Deed Book 151, Page 206.
    assert mdp.parse_reference_line("DT 151/206")["doc_type"] == "deed-of-trust"


def test_other_types_below_book_238_are_deeds():
    assert mdp.parse_reference_line("100/50 plat")["doc_type"] == "deed"


@pytest.mark.parametrize("line", ["Book/Page", "Book Page", "DT", "ABC/12", "500"])
def test_parse_reference_line_rejects_non_references(line):
    assert mdp.parse_reference_line(line) is None


@pytest.mark.parametrize(
    "line, kind",
    [
        ("Cause 1994-175 - Ollie Wahl Hobson", "chancery cause"),
        ("cause: 1994-175", "chancery cause"),
        ("1994-175 cause", "chancery cause"),
        ("Case 88-412", "chancery case"),
        ("Chancery 1994-175", "chancery case"),
        ("Will of James Glen Steinwinder", "will"),
        ("Will 5/100", "will"),
    ],
)
def test_court_records_are_not_land_records(line, kind):
    # Court case numbers look like book-page references but are not
    assert mdp.court_record_kind(line) == kind
    assert mdp.parse_reference_line(line) is None


@pytest.mark.parametrize(
    "line", ["3799/446", "DT 502/308", "501-50 plat", "500/100 - Will Smith"]
)
def test_land_records_are_not_court_records(line):
    assert mdp.court_record_kind(line) is None


def test_process_txt_file_skips_court_records(tmp_path, capsys):
    txt = tmp_path / "docs.txt"
    txt.write_text(
        "3428/182\nCause 1994-175 - Ollie Wahl Hobson\nWill of James Glen Steinwinder\n",
        encoding="utf-8",
    )

    docs = mdp.process_txt_file(str(txt))

    assert [(d["book"], d["page"]) for d in docs] == [(3428, 182)]
    out = capsys.readouterr().out
    assert "Skipping line 2 (chancery cause" in out
    assert "Skipping line 3 (will" in out
    assert "Could not parse" not in out


def test_process_txt_file_parses_every_reference(tmp_path, capsys):
    lines = [
        "Book/Page",
        "232/392",
        "DT 502/308",
        "163/654",
        "177/605",
        "DT 338/83",
        "DT 151/206",
        "13/22",
        "11/213",
        "7/477",
        "7/480",
        "14/466",
        "14/468",
        "14/547",
        "CCC/165",
        "MMM/446",
        "MMM/406",
        "QQQ/9",
        "SS/52",
        "S/646",
        "X/310",
        "CCC/160",
        "M/44",
        "M/156",
        "M/187",
        "L/314",
        "L/306",
        "J/360",
        "I/680",
        "H/155",
        "H/103",
        "500/100 deed book",
    ]
    txt = tmp_path / "Docs to Get.txt"
    txt.write_text("\n".join(lines), encoding="utf-8")

    docs = mdp.process_txt_file(str(txt))

    assert "Could not parse" not in capsys.readouterr().out
    assert len(docs) == len(lines) - 1
    by_ref = {d["original_ref"]: d for d in docs}
    assert by_ref["DT 502/308"]["doc_type"] == "deed-of-trust"
    assert by_ref["CCC/165"]["book"] == "CCC"
    assert by_ref["500/100 deed book"]["book"] == 500


def test_process_txt_file_handles_utf8_bom(tmp_path):
    txt = tmp_path / "docs.txt"
    txt.write_text("DT 502/308\n", encoding="utf-8-sig")
    assert mdp.process_txt_file(str(txt))[0]["doc_type"] == "deed-of-trust"


# =============================================================================
# File naming / GCS paths
# =============================================================================


def test_local_filename_distinguishes_series():
    assert mdp.local_filename(502, 308, "deed") == "0502-0308.pdf"
    assert mdp.local_filename(502, 308, "deed-of-trust") == "DT-0502-0308.pdf"
    assert mdp.local_filename("CCC", 165, "deed") == "CCC-0165.pdf"


def test_build_gcs_path():
    assert (
        mdp.build_gcs_path(14, 466, "deed") == "documents/historical/deed/0014-0466.pdf"
    )
    assert (
        mdp.build_gcs_path(502, 308, "deed-of-trust")
        == "documents/mid-early/deed-of-trust/0502-0308.pdf"
    )
    assert (
        mdp.build_gcs_path("CCC", 165, "deed")
        == "documents/historical/deed/CCC-0165.pdf"
    )


class FakeBlob:
    def __init__(self, name, existing):
        self.name = name
        self._existing = existing

    def exists(self):
        return self.name in self._existing


class FakeBucket:
    def __init__(self, names):
        self.names = set(names)
        self.listed = []

    def blob(self, name):
        return FakeBlob(name, self.names)

    def list_blobs(self, prefix, delimiter=None):
        self.listed.append(prefix)
        it = mock.MagicMock()
        it.__iter__.return_value = iter([])
        it.prefixes = {
            prefix + n[len(prefix) :].split("/")[0] + "/"
            for n in self.names
            if n.startswith(prefix)
        }
        return it


def test_find_gcs_blob_deed_checks_other_type_folders():
    bucket = FakeBucket(["documents/historical/unknown/0151-0206.pdf"])
    blob = mdp.find_gcs_blob(bucket, 151, 206, "deed")
    assert blob.name == "documents/historical/unknown/0151-0206.pdf"


def test_find_gcs_blob_deed_of_trust_never_uses_deed_folders():
    bucket = FakeBucket(
        [
            "documents/historical/unknown/0151-0206.pdf",
            "documents/historical/deed/0151-0206.pdf",
        ]
    )
    assert mdp.find_gcs_blob(bucket, 151, 206, "deed-of-trust") is None
    assert bucket.listed == []


def test_find_gcs_blob_deed_never_uses_deed_of_trust_folder():
    bucket = FakeBucket(["documents/mid-early/deed-of-trust/0502-0308.pdf"])
    assert mdp.find_gcs_blob(bucket, 502, 308, "deed") is None


def test_find_gcs_blob_deed_of_trust_exact_path():
    bucket = FakeBucket(["documents/mid-early/deed-of-trust/0502-0308.pdf"])
    blob = mdp.find_gcs_blob(bucket, 502, 308, "deed-of-trust")
    assert blob.name == "documents/mid-early/deed-of-trust/0502-0308.pdf"


# =============================================================================
# Web lookup result parsing and selection
# =============================================================================


def _result_block(type_code, book, page, nature, image_ids):
    """One result as rendered by drupal-deed-record-lookup.php (copied from the live markup)."""
    links = "".join(
        f'<a href="/elected-offices/chancery-clerk/court-house-search/pdf-records.php?image={i}" '
        f'target="_blank" >Download Image {n}</a>'
        for n, i in enumerate(image_ids, start=1)
    )
    return f"""
                    <div>
                        <h2 style="margin-bottom:0px;">Grantor: <em>GRANTOR {book}-{page}<br />Grantee: <em>GRANTEE</h2>
                        <strong>
                        Nature: <em>{nature}</em>
                        </strong>
                        <table>
                            <tr>
                                <td>Type:&nbsp;<em>{type_code} </em></td>
                                <td>Book:&nbsp;<em>{book}</em></td>
                                <td>Page:&nbsp;<em>{page}</em></td>
                                <td>&nbsp;
                                </td>
                            </tr>
                            <tr>
                                <td>Section:&nbsp;<em>14</em></td>
                                <td>Township:&nbsp;<em>08N</em></td>
                                <td>Range:&nbsp;<em>01E</em></td>
                                <td>Date&nbsp;Recorded:&nbsp;<em>1/6/1984</em></td>
                            </tr>
                        </table>
                        <a href="#">More Information</a>&nbsp;&nbsp;<strong>IMAGES: </strong>{links}</div>"""


def _results_page(*blocks):
    return f'<html><body><article id="content"><p>New Search</p>{"".join(blocks)}</article></body></html>'


MIXED_RESULTS = _results_page(
    _result_block("W", 502, 308, "DEED", ["111"]),
    _result_block("T", 502, 308, "DEED OF TRUST", ["222", "223"]),
    _result_block("X", 502, 309, "PLAT FILED", []),
)


def test_parse_html_results_reads_every_result():
    results = mdp.MadisonCountyDownloader._parse_html_results(MIXED_RESULTS)
    assert [(r.doc_type, r.book, r.page, r.image_id) for r in results] == [
        ("W", 502, 308, "111"),
        ("T", 502, 308, "222"),
        ("X", 502, 309, None),
    ]
    assert results[1].doc_nature == "DEED OF TRUST"
    assert results[0].grantor == "GRANTOR 502-308"
    assert results[0].date_recorded == "1/6/1984"


def test_select_result_picks_matching_series():
    results = mdp.MadisonCountyDownloader._parse_html_results(MIXED_RESULTS)
    assert mdp.select_result(results, 502, 308, "deed").image_id == "111"
    assert mdp.select_result(results, 502, 308, "deed-of-trust").image_id == "222"


def test_select_result_rejects_wrong_series_and_book():
    deed_only = mdp.MadisonCountyDownloader._parse_html_results(
        _results_page(_result_block("W", 502, 308, "DEED", ["111"]))
    )
    assert mdp.select_result(deed_only, 502, 308, "deed-of-trust") is None
    assert mdp.select_result(deed_only, 503, 308, "deed") is None


def test_select_result_matches_lettered_book():
    results = mdp.MadisonCountyDownloader._parse_html_results(
        _results_page(_result_block("W", "CCC", 165, "DEED", ["999"]))
    )
    assert mdp.select_result(results, "CCC", 165, "deed").image_id == "999"


def _response(content, content_type):
    resp = mock.Mock()
    resp.content = content.encode() if isinstance(content, str) else content
    resp.text = content if isinstance(content, str) else ""
    resp.headers = {"Content-Type": content_type}
    resp.raise_for_status = mock.Mock()
    return resp


def test_download_from_web_saves_deed_of_trust_under_dt_name(tmp_path):
    dl = mdp.MadisonCountyDownloader(download_dir=str(tmp_path), check_gcs=False)
    dl.session = mock.Mock()
    dl.session.get.side_effect = [
        _response(MIXED_RESULTS, "text/html"),
        _response(b"%PDF-1.4 fake", "application/pdf"),
    ]

    result = dl.download_by_book_page(502, 308, "deed-of-trust")

    assert result.success, result.error
    assert Path(result.local_path).name == "DT-0502-0308.pdf"
    lookup_params = dl.session.get.call_args_list[0].kwargs["params"]
    assert lookup_params["doc_type"] == ""
    assert dl.session.get.call_args_list[1].args[0].endswith("image=222")


def test_download_from_web_reports_missing_series(tmp_path):
    dl = mdp.MadisonCountyDownloader(download_dir=str(tmp_path), check_gcs=False)
    dl.session = mock.Mock()
    dl.session.get.return_value = _response(
        _results_page(_result_block("W", 502, 308, "DEED", ["111"])), "text/html"
    )

    result = dl.download_by_book_page(502, 308, "deed-of-trust")

    assert not result.success
    assert "deed of trust" in result.error.lower()
    assert dl.session.get.call_count == 1


def test_download_from_web_rejects_unverifiable_pdf_for_deed_of_trust(tmp_path):
    dl = mdp.MadisonCountyDownloader(download_dir=str(tmp_path), check_gcs=False)
    dl.session = mock.Mock()
    dl.session.get.return_value = _response(b"%PDF-1.4 fake", "application/pdf")

    assert not dl.download_by_book_page(151, 206, "deed-of-trust").success
    assert not list(tmp_path.iterdir())
    assert dl.download_by_book_page(151, 206, "deed").success


def test_download_from_web_explains_connection_refused(tmp_path):
    dl = mdp.MadisonCountyDownloader(download_dir=str(tmp_path), check_gcs=False)
    dl.session = mock.Mock()
    dl.session.get.side_effect = requests.exceptions.ConnectionError(
        "[WinError 10061] refused"
    )

    result = dl.download_by_book_page(14, 466)

    assert not result.success
    assert "tools.madison-co.net" in result.error
    assert "down" in result.error
