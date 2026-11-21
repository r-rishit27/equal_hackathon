"""Vocabulary shared by the engine, the service, the API and the UI (02_LLD.md §4)."""
from __future__ import annotations


class PaymentStatus:
    UNMATCHED = "unmatched"
    NEEDS_REVIEW = "needs_review"
    PARTIALLY_APPLIED = "partially_applied"
    APPLIED = "applied"
    EXCEPTION = "exception"
    NOT_RECEIPT = "not_receipt"
    REVERSED = "reversed"

    # The agent may (re)match a payment only in these states.
    MATCHABLE = (UNMATCHED, NEEDS_REVIEW, PARTIALLY_APPLIED)
    ALL = (UNMATCHED, NEEDS_REVIEW, PARTIALLY_APPLIED, APPLIED, EXCEPTION, NOT_RECEIPT, REVERSED)


class InvoiceStatus:
    OPEN = "open"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    DISPUTED = "disputed"
    WRITTEN_OFF = "written_off"
    VOID = "void"

    APPLICABLE = (OPEN, PARTIALLY_PAID)
    ALL = (OPEN, PARTIALLY_PAID, PAID, DISPUTED, WRITTEN_OFF, VOID)


class ReasonCode:
    """Why money was held back from an invoice (application reason_code)."""
    TDS = "TDS"
    DISCOUNT = "DISCOUNT"
    BANK_CHARGES = "BANK_CHARGES"
    ROUNDING = "ROUNDING"
    SHORT_SUPPLY = "SHORT_SUPPLY"
    DAMAGE = "DAMAGE"
    RATE_DIFF = "RATE_DIFF"
    DEBIT_NOTE = "DEBIT_NOTE"
    FX = "FX"
    DISPUTE = "DISPUTE"
    OTHER = "OTHER"
    ALL = (TDS, DISCOUNT, BANK_CHARGES, ROUNDING, SHORT_SUPPLY, DAMAGE, RATE_DIFF, DEBIT_NOTE, FX, DISPUTE, OTHER)


class ExceptionCode:
    """Why a person parked a payment (payment reason_code when status = exception)."""
    DISPUTE = "DISPUTE"
    DUPLICATE = "DUPLICATE"
    AWAITING_REMITTANCE = "AWAITING_REMITTANCE"
    WRONG_CUSTOMER = "WRONG_CUSTOMER"
    FX = "FX"
    REFUND_DUE = "REFUND_DUE"
    BOUNCE_SUSPECTED = "BOUNCE_SUSPECTED"
    OTHER = "OTHER"
    ALL = (DISPUTE, DUPLICATE, AWAITING_REMITTANCE, WRONG_CUSTOMER, FX, REFUND_DUE, BOUNCE_SUSPECTED, OTHER)


class Flag:
    """Raised by the engine or detectors; any flag forces human review (02_LLD.md §6.4)."""
    CLUE_CONFLICT = "CLUE_CONFLICT"
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"
    AMBIGUOUS_PAYER = "AMBIGUOUS_PAYER"
    CROSS_CUSTOMER = "CROSS_CUSTOMER"
    ADVANCE = "ADVANCE"
    FOREIGN_CURRENCY = "FOREIGN_CURRENCY"
    REMITTANCE_DISAGREES = "REMITTANCE_DISAGREES"
    DISPUTED_INVOICE = "DISPUTED_INVOICE"
    TDS_ON_GROSS = "TDS_ON_GROSS"
    POSSIBLE_BOUNCE = "POSSIBLE_BOUNCE"


class JobReason:
    NEW_PAYMENT = "new_payment"
    REMITTANCE = "remittance"
    NEW_INVOICE = "new_invoice"
    ALIAS_LEARNED = "alias_learned"
    # A payment was applied or unapplied: the same customer's other waiting payments
    # were suggested against invoices whose balances just changed.
    LEDGER_CHANGED = "ledger_changed"
    UNAPPLIED = "unapplied"
    RESOLVED = "resolved"
    MANUAL = "manual"
    SWEEP = "sweep"


class Method:
    AUTO = "auto"
    ACCEPTED = "accepted"
    MANUAL = "manual"
