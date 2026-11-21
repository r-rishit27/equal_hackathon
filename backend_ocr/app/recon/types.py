"""Value types for recon — see docs/bata-recon/02_CLASS_DIAGRAMS.md.

Money and quantities are Decimal everywhere; JSON carries them as strings so
nothing drifts through a float. `to_json` / `from_json` are generic over these
dataclasses so a segment's `extracted_json` and the golden test fixtures load
the same way.
"""
from __future__ import annotations

import dataclasses
import types as _pytypes
import typing
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, TypeVar, Union


# ── Enums ──────────────────────────────────────────────────────────────────────

class DocClass(str, Enum):
    PURCHASE_ORDER = "PURCHASE_ORDER"
    TAX_INVOICE = "TAX_INVOICE"
    INVOICE_ANNEXURE = "INVOICE_ANNEXURE"
    PV_NARRATIVE = "PV_NARRATIVE"
    PV_ANNEXURE_TYPED = "PV_ANNEXURE_TYPED"
    PV_SHEET_SCANNED = "PV_SHEET_SCANNED"
    PV_FIELD_SHEET = "PV_FIELD_SHEET"
    POD = "POD"
    APPROVAL_MEMO = "APPROVAL_MEMO"
    TERMS_CONDITIONS = "TERMS_CONDITIONS"
    DELIVERY_CHALLAN = "DELIVERY_CHALLAN"
    GRN = "GRN"
    MEASUREMENT_SHEET = "MEASUREMENT_SHEET"
    OTHER = "OTHER"


class SegmentKind(str, Enum):
    PURCHASE_ORDER = "PURCHASE_ORDER"
    TAX_INVOICE = "TAX_INVOICE"
    PV_SECTION = "PV_SECTION"
    POD = "POD"
    APPROVAL_MEMO = "APPROVAL_MEMO"
    PAYMENT_ADVICE = "PAYMENT_ADVICE"
    OTHER = "OTHER"
    IGNORED = "IGNORED"


class AuditVerdict(str, Enum):
    VERIFIED = "VERIFIED"
    NOT_DONE = "NOT_DONE"
    NOT_COUNTABLE = "NOT_COUNTABLE"
    NOT_COVERED = "NOT_COVERED"
    ADDITIONAL = "ADDITIONAL"
    UNKNOWN = "UNKNOWN"


class Severity(str, Enum):
    OK = "OK"
    INFO = "INFO"
    REVIEW = "REVIEW"
    BLOCKER = "BLOCKER"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]


_SEVERITY_RANK = {Severity.OK: 0, Severity.INFO: 1, Severity.REVIEW: 2, Severity.BLOCKER: 3}


def max_severity(items) -> Severity:
    best = Severity.OK
    for s in items:
        if s.rank > best.rank:
            best = s
    return best


class LineStatus(str, Enum):
    RATE_HIGHER = "RATE_HIGHER"
    RATE_LOWER = "RATE_LOWER"
    OVER_PO = "OVER_PO"
    OVER_VERIFIED = "OVER_VERIFIED"
    UNDER_BILLED = "UNDER_BILLED"
    UNDER_USED = "UNDER_USED"
    OVER_EXECUTED_CAPPED = "OVER_EXECUTED_CAPPED"
    NOT_DONE = "NOT_DONE"
    NOT_VERIFIABLE = "NOT_VERIFIABLE"
    NOT_IN_PO = "NOT_IN_PO"
    ADDITIONAL_ON_SITE = "ADDITIONAL_ON_SITE"
    DESCRIPTION_CONFLICT = "DESCRIPTION_CONFLICT"
    UOM_CONFLICT = "UOM_CONFLICT"
    DAMAGED_UNMOUNTED = "DAMAGED_UNMOUNTED"
    AUDITOR_REMARK = "AUDITOR_REMARK"
    PCT_CHARGE_MISMATCH = "PCT_CHARGE_MISMATCH"
    ARITHMETIC = "ARITHMETIC"
    NO_EVIDENCE = "NO_EVIDENCE"
    UNCHECKED_READING = "UNCHECKED_READING"
    REPORT_ONLY = "REPORT_ONLY"            # report row that fits no line of this PO (likely another PO)
    MATCHED = "MATCHED"


class MatchMethod(str, Enum):
    EXACT = "EXACT"
    ALIAS = "ALIAS"
    SCORE = "SCORE"
    LLM = "LLM"
    HUMAN = "HUMAN"
    NONE = "NONE"


class ReconStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    NEEDS_LINK = "NEEDS_LINK"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    READY = "READY"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class CaseStatus(str, Enum):
    AWAITING_INVOICE = "AWAITING_INVOICE"
    AWAITING_PO = "AWAITING_PO"
    IN_PROGRESS = "IN_PROGRESS"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    # R5 (Bata, 16 Nov 2026): lines billed outside the PO are not rejected and
    # not paid — the invoice is booked in full and the vendor must issue a credit
    # note for the excess, after which a NEW PO covers the balance. The case waits
    # on that document, so this is a distinct state from "needs review": the next
    # action sits with the vendor, not with a reviewer.
    AWAITING_CREDIT_NOTE = "AWAITING_CREDIT_NOTE"
    # R10 (Bata, 16 Nov 2026): an invoice is usually raised after the audit
    # report, "but sometimes before". A bill with no receipt leg yet is not
    # wrong — it is early. Park it; do not fail it, and do not reconcile it
    # either, because nothing has confirmed the work was done.
    AWAITING_RECEIPT = "AWAITING_RECEIPT"
    RECONCILED = "RECONCILED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class ChargeBasis(str, Enum):
    FIXED = "FIXED"                        # bill the PO amount
    PERCENT_OF_GOODS = "PERCENT_OF_GOODS"  # pct × expected goods subtotal
    MIN = "MIN"                            # lower of the two


class TaxRegime(str, Enum):
    IGST = "IGST"
    CGST_SGST = "CGST_SGST"
    NONE = "NONE"


# ── Shared ─────────────────────────────────────────────────────────────────────

@dataclass(kw_only=True)
class Sourced:
    """A number read from a document, with where it came from and how sure we are.

    Fixtures and hand-entered values may give a bare scalar; `from_json` wraps it.
    """
    value: Decimal | None
    confidence: float = 1.0
    page: int | None = None
    bbox: list[float] | None = None
    raw: str | None = None
    alternatives: list[str] = field(default_factory=list)   # disagreeing reads


def sval(s: Sourced | None) -> Decimal | None:
    return None if s is None else s.value


@dataclass(kw_only=True)
class Party:
    name: str = ""
    gstin: str | None = None
    account: str | None = None


# ── Extracted documents ────────────────────────────────────────────────────────

@dataclass(kw_only=True)
class ExtractedDoc:
    segment_id: str | None = None
    extractor_version: str = "v1"
    warnings: list[str] = field(default_factory=list)


@dataclass(kw_only=True)
class PenaltyTerm:
    days_from: int
    days_to: int | None
    pct: Decimal
    per_day: bool = False


@dataclass(kw_only=True)
class POLine:
    sno: int
    description: str
    unit: str | None
    qty: Decimal
    unit_price: Decimal
    amount: Decimal
    delivery_date: date | None = None
    id: str | None = None

    @property
    def key(self) -> str:
        return self.id or f"po:{self.sno}"


@dataclass(kw_only=True)
class ExtractedPO(ExtractedDoc):
    po_number: str
    revision: int = 1
    po_date: date | None = None
    vendor: Party = field(default_factory=Party)
    buyer_gstin: str | None = None
    store_sn: str | None = None
    store_name: str | None = None
    payment_terms: str | None = None
    requisition_no: str | None = None
    requisition_name: str | None = None
    delivery_date: date | None = None
    lines: list[POLine] = field(default_factory=list)
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None
    penalties: list[PenaltyTerm] = field(default_factory=list)


@dataclass(kw_only=True)
class InvoiceLine:
    key: str
    description: str
    sno: int | None = None
    hsn: str | None = None
    unit: str | None = None
    qty: Sourced | None = None
    rate: Sourced | None = None
    amount: Sourced | None = None
    tax_rate: Decimal | None = None
    is_charge: bool = False
    charge_pct: Decimal | None = None
    # A section heading carrying the subtotal of other lines on the same
    # invoice (rollup.py). Not a charge: counting it bills the work twice.
    is_rollup: bool = False


@dataclass(kw_only=True)
class TaxBlock:
    regime: TaxRegime = TaxRegime.NONE
    cgst: Decimal = Decimal("0")
    sgst: Decimal = Decimal("0")
    igst: Decimal = Decimal("0")
    rate: Decimal | None = None


@dataclass(kw_only=True)
class Correction:
    field: str
    printed: str
    handwritten: str
    page: int | None = None


@dataclass(kw_only=True)
class ExtractedInvoice(ExtractedDoc):
    invoice_no: str
    invoice_date: date | None = None
    irn: str | None = None
    vendor: Party = field(default_factory=Party)
    buyer_gstin: str | None = None
    place_of_supply: str | None = None      # state code "29" or name
    po_ref: str | None = None
    payment_terms: str | None = None
    header_lines: list[InvoiceLine] = field(default_factory=list)
    annexure_lines: list[InvoiceLine] = field(default_factory=list)
    printed_subtotal: Decimal | None = None   # what the annexure prints as goods/sub total
    taxable: Decimal | None = None
    tax: TaxBlock = field(default_factory=TaxBlock)
    round_off: Decimal = Decimal("0")
    total: Decimal | None = None
    corrections: list[Correction] = field(default_factory=list)

    @property
    def lines(self) -> list[InvoiceLine]:
        """The lines to reconcile: the annexure when there is one."""
        return self.annexure_lines or self.header_lines


@dataclass(kw_only=True)
class EvidenceRow:
    key: str
    item: str
    sno: int | None = None
    asset_code: str | None = None
    unit: str | None = None
    po_qty: Decimal | None = None
    vendor_qty: Sourced | None = None
    audit_qty: Sourced | None = None
    audit_qty_raw: str | None = None
    remark: str | None = None
    verdict: AuditVerdict | None = None      # None → classified by rules.VerdictClassifier
    mounted: int | None = None
    unmounted: int | None = None
    damaged: int | None = None
    rate: Decimal | None = None
    rate_after_discount: Decimal | None = None
    # The row total as PRINTED on the report. Reports extend the ORDERED
    # quantity, not the audited one, so this is checked against po_qty × rate
    # and never quietly used as what the site supports.
    amount: Decimal | None = None
    row_type: str = "po"                     # po | additional
    needs_review: bool = False


@dataclass(kw_only=True)
class PVSection(ExtractedDoc):
    auditor: str | None = None
    store_sn: str | None = None
    verification_date: date | None = None
    vendor: Party = field(default_factory=Party)
    section_title: str | None = None
    layout: str = "generic"                  # jpc_typed | matolia_scan | generic
    rows: list[EvidenceRow] = field(default_factory=list)


@dataclass(kw_only=True)
class Receipt:
    stamp_text: str | None = None
    receiver: str | None = None
    date: date | None = None


@dataclass(kw_only=True)
class ExtractedPOD(ExtractedDoc):
    waybill_no: str | None = None
    carrier: str | None = None
    invoice_nos: list[str] = field(default_factory=list)
    total_invoice_value: Decimal | None = None
    packages: int | None = None
    weight: Decimal | None = None
    ship_date: date | None = None
    receipt: Receipt = field(default_factory=Receipt)


@dataclass(kw_only=True)
class PaymentAdviceLine:
    """One settled document on a remittance advice.

    `reference` is the payer's own document number for the bill being settled
    (an ERP reference such as `SL8069260000321`), which is usually NOT the
    vendor's invoice number — matching has to allow for both.
    """
    reference: str
    document_date: date | None = None
    document_type: str | None = None          # "Vendor Invoice", "Credit Memo", …
    credit_debit: str | None = None           # Credit | Debit
    base_amount: Decimal | None = None
    tds_amount: Decimal = Decimal("0")
    net_amount: Decimal | None = None


@dataclass(kw_only=True)
class ExtractedPaymentAdvice(ExtractedDoc):
    """A remittance advice (vocabulary §2.6, PAYMENT leg).

    Direction is deliberately not assumed: the same shape serves a payment we
    make to a supplier and one a customer makes to us, so the fields are payer
    and payee rather than vendor and buyer.
    """
    payer_name: str | None = None
    payer_gstin: str | None = None
    payee_name: str | None = None
    payee_gstin: str | None = None
    payment_date: date | None = None
    clearing_date: date | None = None
    utr_no: str | None = None
    cheque_no: str | None = None
    payment_doc_no: str | None = None
    profit_center: str | None = None
    segment_name: str | None = None
    run_id: str | None = None
    lines: list[PaymentAdviceLine] = field(default_factory=list)
    total_base: Decimal | None = None
    total_tds: Decimal | None = None
    total_net: Decimal | None = None

    @property
    def references(self) -> list[str]:
        return [l.reference for l in self.lines if l.reference]


@dataclass(kw_only=True)
class Approval:
    approver: str
    status: str
    date: date | None = None
    remark: str | None = None


@dataclass(kw_only=True)
class ExtractedMemo(ExtractedDoc):
    memo_ref: str | None = None
    subject: str | None = None
    store_sn: str | None = None
    vendor_name: str | None = None
    approvals: list[Approval] = field(default_factory=list)
    body: str | None = None


@dataclass(kw_only=True)
class ExtractedOther(ExtractedDoc):
    llm_label: str | None = None
    summary: str | None = None
    key_values: dict[str, str] = field(default_factory=dict)
    rows: list[EvidenceRow] = field(default_factory=list)


# ── Matching ───────────────────────────────────────────────────────────────────

@dataclass(kw_only=True)
class PairScore:
    rate: float
    unit: float
    name: float
    variant: float
    qty: float
    position: float
    total: float
    conflicts: list[str] = field(default_factory=list)


@dataclass(kw_only=True)
class MatchPair:
    po_key: str | None          # None = explicitly "not in this PO"
    other_key: str
    score: float
    method: MatchMethod
    conflicts: list[str] = field(default_factory=list)
    reason: str | None = None


# ── Engine ─────────────────────────────────────────────────────────────────────

@dataclass(kw_only=True)
class RuleConfig:
    rate_abs_tol: Decimal = Decimal("0.50")
    rate_rel_tol: Decimal = Decimal("0.001")
    qty_tol: Decimal = Decimal("0.01")
    money_tol: Decimal = Decimal("1.00")
    cap_at_po: bool = True
    flag_under_use: bool = True

    # ── Bata's confirmed rules (docs/reconciliation/QUESTIONS_FOR_BATA.md, 16 Nov 2026) ───────────
    # R2: "the rate is fixed on the PO" and may not change — any variation needs
    # a new PO. With this on, the rate tolerances above do not apply to a rate
    # ABOVE the PO: an exact match is required. Off by default so existing
    # tenants keep the tolerance behaviour they were configured with.
    rate_must_equal: bool = False
    # R7: an invoice over the GRN by more than this is an exception for the
    # costing team. Absolute rupees, not a percentage — Bata was asked directly
    # about a percentage band and answered "₹100, whichever is lower".
    invoice_vs_receipt_tol: Decimal = Decimal("100.00")
    # Confirmed by Bata, 18 Nov 2026: the threshold is **per invoice**, not per
    # line. Kept as a setting because another client may well scope it per line.
    variance_scope: str = "invoice"          # invoice | line
    # R6: "one invoice cannot be processed against two POs" — prohibited, and
    # vendors have been told so.
    single_po_per_invoice: bool = True
    # How an auditor's blank cell with no remark is read (see 07_TEST_PLAN §3.3).
    blank_audit_means: AuditVerdict = AuditVerdict.UNKNOWN
    # charge description regex → basis; first match wins
    charge_rules: dict[str, ChargeBasis] = field(default_factory=lambda: {
        r"packing|forwarding": ChargeBasis.FIXED,
    })
    # extra remark regex → verdict, checked before the built-in patterns
    verdict_overrides: dict[str, AuditVerdict] = field(default_factory=dict)


@dataclass(kw_only=True)
class HeaderCheck:
    code: str
    label: str
    severity: Severity
    passed: bool
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(kw_only=True)
class LineResult:
    ord: int
    kind: str                                 # po | not_in_po | additional
    description: str
    po_key: str | None = None
    invoice_key: str | None = None
    evidence_key: str | None = None
    invoice_text: str | None = None
    evidence_text: str | None = None
    unit: str | None = None
    po_qty: Decimal | None = None
    verified_qty: Decimal | None = None
    # What the site report says the work is worth: the rate it carries — after
    # the discount where it prints one, since that is the rate the parties
    # settled on — and that rate times the quantity the auditor certified.
    # Many reports carry no rate at all, and then both stay None.
    verified_rate: Decimal | None = None
    verified_amt: Decimal | None = None
    vendor_qty: Decimal | None = None
    # The fourth way: what the goods receipt says actually arrived. From a
    # Dynamics GRN extract, which is per line. A delivery proof usually cannot
    # fill this — it proves packages, not items (V§1) — except on a bill with a
    # single line, where the consignment has nowhere else to be.
    received_qty: Decimal | None = None
    # What the receipt is worth. From a GRN this is the line's booked value,
    # which excludes tax; from a delivery proof it is the carrier's declared
    # consignment value, which includes it — `receipt_basis` says which.
    received_amt: Decimal | None = None
    # How the receipt figure was arrived at: "grn" when an extract said so,
    # "single_line_consignment" when a delivery proof's value left only one
    # reading. A derived number must never look like a read one.
    receipt_basis: str | None = None
    billed_qty: Decimal = Decimal("0")
    expected_qty: Decimal = Decimal("0")
    po_rate: Decimal | None = None
    billed_rate: Decimal | None = None
    expected_amt: Decimal = Decimal("0")
    billed_amt: Decimal = Decimal("0")
    delta: Decimal = Decimal("0")
    verdict: AuditVerdict | None = None
    statuses: list[LineStatus] = field(default_factory=list)
    severity: Severity = Severity.OK
    match_method: MatchMethod = MatchMethod.NONE
    match_score: float = 0.0
    conflicts: list[str] = field(default_factory=list)
    remark: str | None = None
    is_charge: bool = False
    needs_review_cell: bool = False
    # The prescribed next action when the client's process fixes one (R5: an
    # out-of-PO line is resolved by a vendor credit note plus a new PO). Shown to
    # the reviewer so the queue says what to do, not just what is wrong.
    remedy: str | None = None


@dataclass(kw_only=True)
class ReconSummary:
    po_total: Decimal | None
    expected_goods: Decimal
    expected_total: Decimal
    billed_goods: Decimal
    billed_total: Decimal
    # The invoice's own total, tax included. Reconciliation runs on the taxable
    # amount, but a delivery proof and a remittance advice both state the GROSS
    # figure — comparing either against the taxable sum reports a difference of
    # exactly the tax on every document.
    invoice_total: Decimal | None = None
    money_at_risk: Decimal
    under_billed: Decimal
    counts: dict[str, int]
    status: CaseStatus
    # How much of what is being billed rests on a pairing we are sure of,
    # weighted by money: 1.0 when every billed rupee sits on an exact or
    # human-confirmed match, lower as value hangs on fuzzy ones. A mean over
    # LINES would let a shaky ₹5,00,000 pairing hide behind forty tidy ₹500
    # ones, which is the wrong way round.
    # None when there is nothing to be confident ABOUT — no PO has arrived, so
    # nothing has been paired. Reporting that as 0 would put a case waiting on
    # a document at the bottom of a confidence chart beside a case whose
    # pairings are genuinely bad, which are not the same problem at all.
    # Section headings excluded from the billing, with what they said. Shown,
    # never silent: a line dropped from an invoice without a word is how an
    # understated bill gets paid.
    rollup_lines: list[dict] = field(default_factory=list)
    confidence: Decimal | None = Decimal("1")
    # Per supporting document, how much of the billed value it actually
    # accounts for: the PO leg by how well the lines paired, the audit leg by
    # how much of the money the auditor certified, the receipt and payment
    # legs by whether they cover the bill. None where that document has not
    # arrived — an absent report is not a badly performing one.
    leg_cover: dict[str, float | None] = field(default_factory=dict)
    # The lines dragging it down, worst money first, for a reviewer who wants
    # to know what to look at rather than just that something is uncertain.
    confidence_weakest: list[dict] = field(default_factory=list)


@dataclass(kw_only=True)
class ReconInput:
    po: ExtractedPO | None
    invoice: ExtractedInvoice | None
    evidence: list[PVSection] = field(default_factory=list)
    pods: list[ExtractedPOD] = field(default_factory=list)
    memos: list[ExtractedMemo] = field(default_factory=list)
    invoice_matches: list[MatchPair] = field(default_factory=list)   # po_key ↔ invoice line key
    evidence_matches: list[MatchPair] = field(default_factory=list)  # po_key ↔ evidence row key
    prior_billed_qty: dict[str, Decimal] = field(default_factory=dict)   # po_key → qty billed on earlier invoices
    prior_billed_value: Decimal = Decimal("0")
    # The receipt leg's taxable value — for Bata, the GRN total read from
    # Microsoft Dynamics (plan §7). None means "no receipt leg yet", and the
    # ₹100 variance check abstains rather than passing.
    receipt_total: Decimal | None = None
    # Which side of the invoice `receipt_total` should be held against:
    # "taxable" for a Dynamics GRN, which books goods at the PO price, and
    # "gross" for a carrier's declared consignment value, which includes tax.
    receipt_basis: str = "taxable"
    # The PAYMENT leg: the remittance advice that settles this invoice.
    payment: ExtractedPaymentAdvice | None = None
    # GRN lines for this case's PO (grn.GrnLine), when an MSD extract has been
    # loaded. Used to check the GRN against what the auditor certified (R3/R8).
    receipt_lines: list = field(default_factory=list)
    other_invoice_numbers: list[str] = field(default_factory=list)      # same supplier, other bills
    # Checks a person has already answered, by check code. A confirmation is
    # about the exact thing they were shown — `shown` records it — so a
    # re-extraction that changes the document asks again instead of coasting
    # on an answer given about different words.
    confirmed_checks: dict[str, dict] = field(default_factory=dict)
    config: RuleConfig = field(default_factory=RuleConfig)


@dataclass(kw_only=True)
class ReconResult:
    header: list[HeaderCheck]
    lines: list[LineResult]
    summary: ReconSummary
    engine_version: str


# ── JSON ───────────────────────────────────────────────────────────────────────

def to_json(obj: Any) -> Any:
    """Dataclasses/enums/Decimal/date → plain JSON values (Decimal as str)."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_json(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): to_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_json(v) for v in obj]
    return obj


T = TypeVar("T")
_HINTS: dict[type, dict[str, Any]] = {}


def _hints(cls: type) -> dict[str, Any]:
    if cls not in _HINTS:
        _HINTS[cls] = typing.get_type_hints(cls)
    return _HINTS[cls]


def _coerce(tp: Any, value: Any) -> Any:
    if value is None:
        return None
    origin = typing.get_origin(tp)
    if origin in (Union, _pytypes.UnionType):
        args = [a for a in typing.get_args(tp) if a is not type(None)]
        return _coerce(args[0], value) if len(args) == 1 else value
    if origin in (list, tuple, set):
        (inner,) = typing.get_args(tp)[:1] or (Any,)
        return [_coerce(inner, v) for v in value]
    if origin is dict:
        k, v = typing.get_args(tp)
        return {_coerce(k, kk): _coerce(v, vv) for kk, vv in value.items()}
    if tp is Sourced and not isinstance(value, dict):
        return Sourced(value=Decimal(str(value)))
    if isinstance(tp, type):
        if dataclasses.is_dataclass(tp):
            return from_json(tp, value)
        if issubclass(tp, Enum):
            return tp(value)
        if tp is Decimal:
            return Decimal(str(value))
        if tp is date:
            return value if isinstance(value, date) else date.fromisoformat(str(value))
        if tp in (int, float, str, bool):
            return tp(value)
    return value


def from_json(cls: type[T], data: dict[str, Any]) -> T:
    """Inverse of `to_json` for any dataclass above. Unknown keys are ignored."""
    hints = _hints(cls)
    kwargs = {}
    for f in dataclasses.fields(cls):
        if f.name in data:
            kwargs[f.name] = _coerce(hints[f.name], data[f.name])
    return cls(**kwargs)
