"""fit_contract_text: a long contract keeps its opening and closing pages."""
import re

from backend_ocr.app.review.comm_extraction_worker import fit_contract_text


def test_short_contract_is_untouched():
    assert fit_contract_text(["a", "b"]) == "a\n\nb"


def test_long_contract_keeps_first_and_last_pages_whole():
    pages = [f"--- Page {i} ---\n" + "x" * 2400 for i in range(1, 15)]
    out = fit_contract_text(pages, limit=20000)
    kept = [int(n) for n in re.findall(r"Page (\d+)", out)]
    assert len(out) <= 20000
    assert kept[0] == 1 and kept[-1] == 14          # opening and the annexures
    assert kept == sorted(kept) and "middle pages omitted" in out


def test_one_huge_page_is_cut_not_dropped():
    assert len(fit_contract_text(["y" * 50000], limit=1000)) == 1000
