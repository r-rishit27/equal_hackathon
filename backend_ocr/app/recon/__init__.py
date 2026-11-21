"""Recon: purchase order ↔ invoice ↔ on-ground evidence reconciliation.

Design: docs/bata-recon/ (start at README.md). The engine (rules.py, engine.py,
match.py) is pure — typed inputs in, typed results out, no DB and no network —
so everything non-deterministic (reading, classification, LLM adjudication)
happens before it and can be cached.
"""
