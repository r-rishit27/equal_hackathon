"""Thin wrapper over the shared spreadsheet parser.

Recon reads .xlsx/.csv through `core.vendor_doc_tables.parse_spreadsheet` rather
than its own reader, so header detection and Indian number coercion behave the
same everywhere. The wrapper exists for two reasons: it keeps the import local
(openpyxl is heavy and only needed on this path), and a corrupt upload must come
back as "no sheets" for the caller to report, not as a traceback.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def parse_spreadsheet_safe(file_name: str, contents: bytes) -> list:
    """`[(sheet_meta, [(row_no, {column: value}), …]), …]`, or `[]` if unreadable."""
    try:
        from ..core.vendor_doc_tables import parse_spreadsheet
        return parse_spreadsheet(file_name, contents)
    except Exception:
        logger.exception("[recon] could not read spreadsheet %s", file_name)
        return []
