"""Deployment ownership for agents that normally run in the API or pipeline."""

import os

WORKER_AGENTS = (
    "communication", "compliance", "verification", "recon", "payable",
    "contract", "tds", "gst", "receivable",
)


def is_external(name: str) -> bool:
    configured = {value.strip() for value in os.getenv("ONSUMM_EXTERNAL_AGENTS", "").split(",")}
    return name in configured
