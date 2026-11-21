"""Named rule profiles, and R_EARLY_INVOICE (plan §5, rule R10)."""
import asyncio
from decimal import Decimal as D

from backend_ocr.app.recon import profiles
from backend_ocr.app.recon.assemble import reconcile
from backend_ocr.app.recon.types import (
    CaseStatus, ExtractedInvoice, ExtractedPO, InvoiceLine, MatchPair, POLine, PVSection, ReconInput,
    RuleConfig, Sourced,
)


# ── profiles ──────────────────────────────────────────────────────────────────

def test_default_profile_is_the_shipped_config():
    assert profiles.resolve("default") == RuleConfig()
    assert profiles.resolve(None) == RuleConfig()


def test_bata_profile_matches_every_confirmed_rule():
    b = profiles.resolve("bata")
    assert b.rate_must_equal is True            # R2: the PO rate is fixed
    assert b.cap_at_po is True                  # R2/R3: payable capped at the PO
    assert b.invoice_vs_receipt_tol == D("100.00")   # R7
    assert b.variance_scope == "invoice"        # confirmed 18 Nov 2026
    assert b.single_po_per_invoice is True      # R6


def test_the_default_is_untouched_by_the_bata_profile():
    """Existing tenants must not inherit another client's policy."""
    assert RuleConfig().rate_must_equal is False
    assert profiles.resolve("default").rate_must_equal is False


def test_name_matching_is_forgiving():
    assert profiles.resolve("BATA") == profiles.resolve(" bata ") == profiles.BATA


def test_an_unknown_profile_falls_back_to_default_rather_than_raising():
    """A typo in a tenant setting must not stop reconciliation.

    The default is also the conservative direction: wider tolerances flag less,
    they never cause an overpayment the tighter rules would have caught.
    """
    assert profiles.resolve("btaa") == RuleConfig()


def test_overrides_apply_on_top_without_mutating_the_profile():
    cfg = profiles.resolve("bata", invoice_vs_receipt_tol=D("500"))
    assert cfg.invoice_vs_receipt_tol == D("500")
    assert cfg.rate_must_equal is True, "the rest of the profile survives"
    assert profiles.BATA.invoice_vs_receipt_tol == D("100.00"), "the profile itself is unchanged"


def test_describe_exposes_every_money_deciding_setting():
    d = profiles.describe(profiles.BATA)
    for k in ("rate_must_equal", "cap_at_po", "invoice_vs_receipt_tol", "variance_scope",
              "single_po_per_invoice"):
        assert k in d
    assert d["invoice_vs_receipt_tol"] == "100.00"


# ── selecting a profile per tenant ────────────────────────────────────────────

class _FakeRepo:
    def __init__(self, name=None, boom=False):
        self.name, self.boom = name, boom

    async def tenant_rule_profile(self, tenant):
        if self.boom:
            raise RuntimeError("settings table unreachable")
        return self.name


def _pipe(repo, config=None):
    from backend_ocr.app.recon.pipeline import ReconPipeline
    return ReconPipeline(repo, config=config)


def test_tenant_setting_picks_the_profile():
    cfg, name = asyncio.run(_pipe(_FakeRepo("bata"))._config_for("t1"))
    assert name == "bata" and cfg.rate_must_equal is True


def test_no_setting_means_the_default_profile():
    cfg, name = asyncio.run(_pipe(_FakeRepo(None))._config_for("t1"))
    assert name == "default" and cfg == RuleConfig()


def test_an_injected_config_overrides_the_tenant_setting():
    """Tests and one-off runs must be able to pin the rules explicitly."""
    explicit = RuleConfig(invoice_vs_receipt_tol=D("7"))
    cfg, name = asyncio.run(_pipe(_FakeRepo("bata"), config=explicit)._config_for("t1"))
    assert cfg is explicit and name == "explicit"


def test_an_unreadable_setting_does_not_stop_reconciliation():
    """If the settings table is down, reconcile under the default rather than fail.

    A recon that refuses to run is worse than one that runs conservatively.
    """
    cfg, name = asyncio.run(_pipe(_FakeRepo(boom=True))._config_for("t1"))
    assert cfg == RuleConfig() and name == "default"


# ── R10 / R_EARLY_INVOICE ─────────────────────────────────────────────────────

def _case(evidence_rows=None, config=None):
    po_line = POLine(sno=1, description="Piping", unit="RFT", qty=D("100"),
                     unit_price=D("620"), amount=D("62000"))
    inv_line = InvoiceLine(key="rl:1", sno=1, description="Piping", unit="RFT",
                           qty=Sourced(value=D("100")), rate=Sourced(value=D("620")),
                           amount=Sourced(value=D("62000")))
    po = ExtractedPO(po_number="PPO00024046", lines=[po_line], total=D("62000"), subtotal=D("62000"))
    inv = ExtractedInvoice(invoice_no="I-1", po_ref="PPO00024046", annexure_lines=[inv_line],
                           taxable=D("62000"), total=D("62000"))
    ev = [PVSection(section_title="s", rows=evidence_rows, layout="generic")] if evidence_rows else []
    return reconcile(ReconInput(po=po, invoice=inv, evidence=ev, config=config or profiles.BATA,
                                invoice_matches=[MatchPair(po_key=po_line.key, other_key="rl:1",
                                                           score=1.0, method="EXACT")]))


def test_an_invoice_with_no_receipt_leg_is_parked_not_failed():
    """Bata: the invoice sometimes arrives before the audit report.

    Parking is the point — failing it would make an ordinary sequence look like
    a problem, and reconciling it would claim evidence that does not exist.
    """
    assert _case().summary.status == CaseStatus.AWAITING_RECEIPT


def test_parking_is_not_a_blocker():
    res = _case()
    assert res.summary.counts.get("BLOCKER", 0) == 0
