"""Contract terms held by a playground flow, and the sheet-vs-bill verdict."""
from backend_ocr.app.domain.playground import checks


def _contract(value, doc="d1", name="Aforv.pdf"):
    return {"doc": {"doc_id": doc, "file_name": name},
            "fields": {"routing_fee": value, "routing_fee_unit": "% of the total invoice amount",
                       "termination_notice": "120"}}


FORMULA = [{"kind": "formula", "config": {
    "steps": '[{"name":"P","expr":"GR * (1 - contract[\\"routing_fee\\"]/100)"}]',
    "aggregates": "[]"}}]


def test_only_terms_the_formula_reads_are_held():
    assert checks.referenced_terms(FORMULA) == {"routing_fee"}


def test_first_run_holds_the_contract_value():
    terms = {}
    notes = checks.settle_terms(terms, _contract("5"), {"routing_fee"})
    assert terms["routing_fee"]["value"] == "5" and notes[0]["status"] == "held"


def test_a_new_contract_does_not_silently_change_the_calculation():
    terms = {}
    checks.settle_terms(terms, _contract("5"), {"routing_fee"})
    val = _contract("10", doc="d2", name="Aforv 2026.pdf")
    notes = checks.settle_terms(terms, val, {"routing_fee"})
    assert val["fields"]["routing_fee"] == "5"            # the formula still sees 5
    assert notes[0]["status"] == "changed" and notes[0]["contract_value"] == "10"
    assert terms["routing_fee"]["pending"]["value"] == "10"


def test_choosing_the_contract_switches_the_next_run():
    terms = {}
    checks.settle_terms(terms, _contract("5"), {"routing_fee"})
    checks.settle_terms(terms, _contract("10", doc="d2"), {"routing_fee"})
    checks.decide_term(terms, "routing_fee", "contract", "ana")
    val = _contract("10", doc="d2")
    notes = checks.settle_terms(terms, val, {"routing_fee"})
    assert val["fields"]["routing_fee"] == "10" and notes[0]["status"] == "held"
    assert "pending" not in terms["routing_fee"]


def test_keeping_the_old_value_is_not_asked_again_for_the_same_contract():
    terms = {}
    checks.settle_terms(terms, _contract("5"), {"routing_fee"})
    checks.settle_terms(terms, _contract("10", doc="d2"), {"routing_fee"})
    checks.decide_term(terms, "routing_fee", "keep", "ana")
    val = _contract("10", doc="d2")
    notes = checks.settle_terms(terms, val, {"routing_fee"})
    assert val["fields"]["routing_fee"] == "5" and notes[0]["status"] == "kept"
    assert "pending" not in terms["routing_fee"]
    # …but a newer contract still asks.
    notes = checks.settle_terms(terms, _contract("12", doc="d3"), {"routing_fee"})
    assert notes[0]["status"] == "changed"


def test_invoice_total_is_picked_by_name_not_position():
    values = {"f": {"totals": {"Total GR@100%": 100.0, "Invoice Amount ": 95.0, "Provision fees": 5.0}}}
    assert checks._invoice_total(values, ["f"]) == ("Invoice Amount", 95.0)
    assert checks._invoice_total({"f": {"totals": {"Provision fees": 5.0}}}, ["f"]) is None


def test_amounts_read_in_indian_grouping():
    from backend_ocr.app.review.adapters.playground_checks import _inr
    assert _inr(2552128.2857) == "₹25,52,128.29"
    assert _inr(999) == "₹999.00"
    assert _inr(-514875.29) == "-₹5,14,875.29"


EMAIL = {"id": "m1", "label": "vendor email “routing fees changed”", "quote": "changed to 10% from 5%"}


def _held_at_5():
    terms = {}
    checks.settle_terms(terms, _contract("5"), {"routing_fee"})
    return terms


def test_a_vendor_email_opens_the_question():
    terms = _held_at_5()
    assert checks.propose_change(terms, "routing_fee", "10", "%", EMAIL) is True
    p = terms["routing_fee"]["pending"]
    assert p["value"] == "10" and p["source"] == "email" and p["doc_id"] == "m1"


def test_an_email_restating_the_current_value_is_not_a_change():
    terms = _held_at_5()
    assert checks.propose_change(terms, "routing_fee", "5", "%", EMAIL) is False
    assert "pending" not in terms["routing_fee"]


def test_a_term_the_flow_never_used_is_not_proposed():
    assert checks.propose_change({}, "routing_fee", "10", "%", EMAIL) is False


def test_a_run_does_not_close_an_email_question_just_because_the_contract_agrees():
    terms = _held_at_5()
    checks.propose_change(terms, "routing_fee", "10", "%", EMAIL)
    val = _contract("5")
    notes = checks.settle_terms(terms, val, {"routing_fee"})
    assert val["fields"]["routing_fee"] == "5"          # still calculates at 5 until decided
    assert notes[0]["status"] == "changed" and notes[0]["contract_value"] == "10"
    assert terms["routing_fee"]["pending"]["source"] == "email"


def test_email_prompt_names_the_known_terms():
    from backend_ocr.app.review.comm_extract import build_user
    u = build_user("AFORV", "Important routing fees changed", "body",
                   {"routing_fee": "5 % of the total invoice amount"})
    assert "Known contract terms: routing_fee = 5 % of the total invoice amount" in u


def test_accepting_an_email_change_amends_the_contract_and_is_not_asked_again():
    terms = _held_at_5()
    checks.propose_change(terms, "routing_fee", "10", "%", EMAIL)
    held = checks.decide_term(terms, "routing_fee", "contract", "ana")
    assert held["value"] == "10" and held["source"] == "email" and held["quote"] == EMAIL["quote"]
    assert held["kept_against"] == {"doc_id": "d1", "value": "5", "file_name": "Aforv.pdf"}
    val = _contract("5")                                # the contract still says 5
    notes = checks.settle_terms(terms, val, {"routing_fee"})
    assert val["fields"]["routing_fee"] == "10" and notes[0]["status"] == "kept"
    assert "pending" not in terms["routing_fee"]
    # A newer contract with a different value still asks.
    notes = checks.settle_terms(terms, _contract("12", doc="d9"), {"routing_fee"})
    assert notes[0]["status"] == "changed"
