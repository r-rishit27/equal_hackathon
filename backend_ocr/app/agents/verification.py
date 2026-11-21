"""Vendor identity findings, using the same adapter and writer as Review Hub."""

from ..review.adapter_worker import ReviewAdapterWorker
from ..review.adapters.vendor_identity import VendorIdentityAdapter


class VerificationWorker(ReviewAdapterWorker):
    def __init__(self):
        super().__init__(adapters=[VendorIdentityAdapter()])
