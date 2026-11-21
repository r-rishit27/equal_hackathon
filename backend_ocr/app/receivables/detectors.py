"""Statement-line detectors that run before matching (04_EDGE_CASES.md §E).

Pure. A credit that is not a customer receipt (interest, an FD sweep, a vendor
refund, a loan disbursal, a transfer between our own accounts) is set aside so
it never pollutes the match rate or gets applied to an invoice. Setting aside is
reversible from the UI. A debit that reverses an earlier credit (bounced cheque,
recalled transfer) is reported so a person can reverse the original payment.
"""
from __future__ import annotations

import re

_NON_RECEIPT = (
    (r"\bINT(EREST)?[\s.]*(PD|PAID|CR|CREDIT)?\b|\bINT\.PD\b|\bSB INT\b", "Interest credit"),
    (r"\bSWEEP\b|\bFD\b.*\b(MATUR|CLOS|PREMAT)|\bAUTO ?SWEEP\b|\bTD (CLOSURE|MATURITY)\b", "Deposit sweep / maturity"),
    (r"\bLOAN\b.*\bDISB|\bDISBURSE?MENT\b|\bOD LIMIT\b|\bCC LIMIT\b", "Loan / limit disbursal"),
    (r"\bREFUND\b|\bREVERSAL OF CHG\b|\bCHG REV\b|\bCHARGES? REV", "Refund / charge reversal"),
    (r"\bOWN A/?C\b|\bSELF\b|\bSELF TRANSFER\b|\bINTERNAL TRANSFER\b|\bTRF TO OWN\b", "Transfer between own accounts"),
    (r"\bCASHBACK\b|\bREWARD\b", "Cashback / reward"),
    (r"\bGST REFUND\b|\bIT REFUND\b|\bINCOME TAX REFUND\b|\bCBDT\b", "Tax refund"),
    (r"\bDIVIDEND\b", "Dividend"),
)

_BOUNCE = re.compile(r"\b(RETURN(ED)?|RTN|BOUNCE[D]?|REV(ERSAL|ERSED)?|DISHONOU?R(ED)?|RECALL(ED)?|UNPAID)\b")


def classify_non_receipt(narration: str | None) -> str | None:
    """A reason when the credit is plainly not a customer paying us, else None."""
    t = (narration or "").upper()
    if not t:
        return None
    for pattern, label in _NON_RECEIPT:
        if re.search(pattern, t):
            return label
    return None


def is_bounce(narration: str | None) -> bool:
    """A debit line that reverses an earlier receipt (cheque return, recall)."""
    return bool(_BOUNCE.search((narration or "").upper()))
