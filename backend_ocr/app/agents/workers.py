"""Compose existing workers without importing the API composition root."""

from importlib import import_module

from .ownership import WORKER_AGENTS

WORKERS = {
    "communication": (("..routers.agent", "run_mailbox_agent", False),),
    "compliance": (
        ("..review.adapter_worker", "ReviewAdapterWorker", True),
        ("..review.agent_worker", "ReviewAgentWorker", True),
    ),
    "verification": ((".verification", "VerificationWorker", True),),
    "recon": (("..recon.worker", "ReconWorker", True),),
    "payable": (
        ("pipelines.approval", "ApprovalWorker", True),
        ("..domain.payments.sweeper", "run_sweeper", False),
    ),
    "contract": (("..review.comm_extraction_worker", "CommExtractionWorker", True),),
    "tds": (("pipelines.tds_processing", "TdsProcessingWorker", True),),
    "gst": (("pipelines.gst_verification", "GstVerificationWorker", True),),
    "receivable": (("..receivables.worker", "CashAppWorker", True),),
}

# Stable locks for standalone replicas. Never derive these from Python's hash().
LOCKS = {name: 875_291_004_430 + index for index, name in enumerate(WORKER_AGENTS)}


def operations(name):
    for module, symbol, is_worker in WORKERS[name]:
        entry = getattr(import_module(module, package=__package__), symbol)
        yield entry().run if is_worker else entry
