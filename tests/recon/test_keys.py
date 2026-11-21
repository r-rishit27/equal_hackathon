"""Stable line identity (recon/keys.py, docs/reconciliation/RECON_IMPLEMENTATION_PLAN.md §6.1).

The property under test is the one the bake-off measured: the same printed line
must yield the same key on a second extraction, and a key that cannot be trusted
must be *marked* untrusted rather than quietly reused.
"""
from decimal import Decimal

import pytest

from backend_ocr.app.recon import keys
from backend_ocr.app.recon.types import EvidenceRow, InvoiceLine, POLine, Sourced


# ── the ladder picks the strongest available basis ────────────────────────────

def test_asset_code_wins_over_everything():
    k = keys.build(leg="receipt", asset_code="FA-1182", sno=3, description="Ductable AHU 8.5 TR")
    assert k.basis == "ASSET_CODE"
    assert k.trusted


def test_printed_no_plus_description_when_no_asset_code():
    k = keys.build(leg="receipt", sno=27, description="Core cutting for refrigerant piping")
    assert k.basis == "PRINTED_NO"
    assert k.trusted


def test_norm_desc_when_no_serial():
    k = keys.build(leg="billing", description="Insulated refrigerant piping 25 mm", unit="RFT",
                   rate=Decimal("620"))
    assert k.basis == "NORM_DESC"
    assert k.trusted


def test_ordinal_is_the_last_resort_and_is_not_trusted():
    k = keys.build(leg="billing", ordinal=4)
    assert k.basis == "ORDINAL"
    assert not k.trusted, "position alone must never carry a decision unattended"


@pytest.mark.parametrize("code", ["", "   ", "-", "NA", "n/a", "nil"])
def test_placeholder_asset_codes_are_not_identity(code):
    k = keys.build(leg="receipt", asset_code=code, sno=9, description="Battery 12V")
    assert k.basis == "PRINTED_NO"


# ── stability: the same printed line survives re-extraction ───────────────────

def test_same_line_same_key_across_extractions():
    first = keys.build(leg="receipt", sno=12, description="Insulated refrigerant piping 25 mm dia")
    again = keys.build(leg="receipt", sno=12, description="Insulated refrigerant piping 25 mm dia")
    assert first.key == again.key


def test_rate_formatting_does_not_change_the_key():
    a = keys.build(leg="billing", description="Core cutting", unit="EA", rate=Decimal("850"))
    b = keys.build(leg="billing", description="Core cutting", unit="EA", rate=Decimal("850.0000"))
    c = keys.build(leg="billing", description="Core cutting", unit="EA", rate=850)
    assert a.key == b.key == c.key


def test_whitespace_and_case_in_description_do_not_change_the_key():
    a = keys.build(leg="receipt", sno=5, description="Core  cutting for piping")
    b = keys.build(leg="receipt", sno=5, description="core cutting for piping")
    assert a.key == b.key


def test_asset_code_punctuation_normalises():
    a = keys.build(leg="receipt", asset_code="FA 1182")
    b = keys.build(leg="receipt", asset_code="fa-1182")
    assert a.key == b.key


# ── separation: different things never collide ────────────────────────────────

def test_legs_are_namespaced():
    po = keys.build(leg="commitment", sno=1, description="Ductable AHU 8.5 TR")
    inv = keys.build(leg="billing", sno=1, description="Ductable AHU 8.5 TR")
    assert po.key != inv.key, "a PO line and an invoice line must not share identity"


def test_different_serial_different_key():
    a = keys.build(leg="receipt", sno=27, description="Core cutting")
    b = keys.build(leg="receipt", sno=28, description="Core cutting")
    assert a.key != b.key


def test_renumbering_is_detectable_not_silent():
    """A parser fix that renumbers lines yields a different key.

    That is correct and deliberate: the decision does not migrate silently, it
    surfaces for re-confirmation (plan §6.3 step 4).
    """
    before = keys.build(leg="receipt", sno=58, description="Core cutting for refrigerant piping")
    after = keys.build(leg="receipt", sno=59, description="Core cutting for refrigerant piping")
    assert before.key != after.key


def test_key_length_is_bounded_for_the_column():
    k = keys.build(leg="receipt", sno=1, description="x" * 4000)
    assert len(k.key) <= 120


# ── duplicates within one document ────────────────────────────────────────────

def test_duplicate_rows_get_distinct_keys_and_lose_trust():
    same = keys.build(leg="billing", description="Core cutting", unit="EA", rate=Decimal("850"))
    out = keys.disambiguate([same, same, same])
    assert len({k.key for k in out}) == 3, "keys must be unique within a document"
    assert out[0].trusted, "the first occurrence keeps its basis"
    assert not out[1].trusted and not out[2].trusted, \
        "later occurrences are positional, so they must be re-confirmed"


def test_a_disambiguated_row_says_it_is_positional():
    """Basis and confidence must agree, or the basis is lying.

    Keeping the original basis left rows reading ASSET_CODE at confidence
    0.40 — claiming to be identified by a printed code while scored as
    identified by position. A reviewer reads the basis to understand how a
    line was recognised; 13 such rows were found in dev.
    """
    same = keys.build(leg="receipt", asset_code="CWIP0001", description="Flush door")
    assert same.basis == "ASSET_CODE" and same.trusted
    out = keys.disambiguate([same, same])
    assert out[0].basis == "ASSET_CODE"
    assert out[1].basis == "ORDINAL", "the second occurrence is paired by position, so say so"
    assert out[1].confidence == keys.CONFIDENCE["ORDINAL"]
    # The key still carries where it came from, so nothing is lost by saying it.
    assert "cwip0001" in out[1].key


def test_disambiguate_is_stable_for_unique_keys():
    a = keys.build(leg="billing", sno=1, description="AHU")
    b = keys.build(leg="billing", sno=2, description="Piping")
    out = keys.disambiguate([a, b])
    assert [k.key for k in out] == [a.key, b.key]


# ── the typed helpers read the right fields ───────────────────────────────────

def test_for_evidence_row_prefers_asset_code():
    row = EvidenceRow(key="tmp:1", sno=4, asset_code="FA-99", item="Battery 12V", unit="EA")
    assert keys.for_evidence_row(row).basis == "ASSET_CODE"


def test_for_evidence_row_uses_discounted_rate_when_present():
    plain = EvidenceRow(key="tmp:1", item="Angle structure", unit="RFT", rate=Decimal("100"))
    disc = EvidenceRow(key="tmp:1", item="Angle structure", unit="RFT", rate=Decimal("100"),
                       rate_after_discount=Decimal("95"))
    assert keys.for_evidence_row(plain).key != keys.for_evidence_row(disc).key


def test_for_invoice_line_reads_the_sourced_rate():
    line = InvoiceLine(key="tmp:1", description="Piping", unit="RFT", rate=Sourced(value=Decimal("620")))
    k = keys.for_invoice_line(line)
    assert k.basis == "NORM_DESC" and k.trusted


def test_for_po_line_is_commitment_leg():
    line = POLine(sno=1, description="Ductable AHU", unit="EA", qty=Decimal("2"),
                  unit_price=Decimal("148000"), amount=Decimal("296000"))
    assert keys.for_po_line(line).key.startswith("commitment/")


def test_trust_floor_matches_the_documented_bases():
    """The plan promises ORDINAL is untrusted and the other three are trusted."""
    assert keys.CONFIDENCE["ORDINAL"] < keys.TRUST_FLOOR
    for basis in ("ASSET_CODE", "PRINTED_NO", "NORM_DESC", "HUMAN"):
        assert keys.CONFIDENCE[basis] >= keys.TRUST_FLOOR
