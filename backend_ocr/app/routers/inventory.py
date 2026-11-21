"""Tenant-scoped inventory planning using bill-line evidence from the operational DB."""

from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field
from psycopg2.extras import RealDictCursor

from ..config import get_conn, put_conn
from ..security.auth import require_role, require_tenant

router = APIRouter(prefix="/api/finance-desk/inventory", tags=["Finance Desk"])

# The source line is the selectable identity. Descriptions are labels, never join keys.
EVIDENCE = """
    SELECT l.line_item_id AS id, l.product_name AS item, l.sap_item_code AS sku,
           l.unit, l.quantity AS billed_units, l.unit_price AS price, b.bill_number, b.bill_date, b.due_date, s.supplier_id, s.name AS supplier,
           s.payment_terms_days
    FROM stg_bill_line_items l
    JOIN stg_bills b ON (b.tenant_id, b.stg_bill_id) = (l.tenant_id, l.stg_bill_id)
    JOIN dim_suppliers s ON (s.tenant_id, s.supplier_id) = (b.tenant_id, b.supplier_id)
    WHERE l.tenant_id = %s AND b.currency_code = 'INR' AND b.bill_date IS NOT NULL
      AND l.unit_price > 0 AND l.quantity > 0 AND NOT coalesce(l.rate_is_percent, false)
      AND nullif(trim(l.unit), '') IS NOT NULL AND nullif(trim(l.product_name), '') IS NOT NULL
"""


def read_prices(line_id=None):
    tenant = require_tenant()
    require_role("admin", "finance_controller", "accountant", "member", "auditor")
    sql = EVIDENCE
    params = [tenant]
    if line_id is not None:
        sql += " AND l.line_item_id = %s"
        params.append(str(line_id))
    sql += " ORDER BY b.bill_date DESC, l.line_item_id"
    conn = get_conn()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        put_conn(conn)


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line_id: UUID
    start: date = Field(le=date(9999, 12, 24))
    on_hand: Decimal = Field(ge=0, le=10**8)
    reserved: Decimal = Field(ge=0, le=10**8)
    daily_demand: Decimal = Field(gt=0, le=10**7)
    lead_days: int = Field(ge=0, le=365)
    pack: Decimal = Field(gt=0, le=10**7, decimal_places=8)
    minimum_order: Decimal = Field(ge=1, le=10**8)
    spendable_paise: int = Field(ge=0, le=10**14)
    inbound_units: Decimal = Field(default=0, ge=0, le=10**8)
    inbound_date: date | None = None
    quote_expiry: date | None = None
    landed_unit_paise: int | None = Field(default=None, gt=0, le=10**11)


def solve_pack_qubo(target: int, minimum: int, capacity: int) -> int:
    """Exact classical solver for the single-item, rank-one pack-count QUBO.

    Encode feasible pack counts as minimum + sum(w_i * x_i), x_i binary.
    Squared distance to the first pack count covering demand gives linear
    coefficients w_i**2 - 2*(target-minimum)*w_i and couplers 2*w_i*w_j.
    All bit strings satisfy the purchasing budget. Zero is handled separately.
    """
    if target == 0 or capacity < minimum:
        return 0
    room = capacity - minimum
    weights = []
    step = 1
    while room:
        weight = min(step, room)
        weights.append(weight)
        room -= weight
        step *= 2

    # After taking the largest bit, the remaining bits represent every integer
    # from zero to their sum. This gives an exact conditional minimum for each
    # bit value, without materializing the dense rank-one coupling matrix.
    packs = minimum
    remaining = capacity - minimum
    for weight in sorted(weights, reverse=True):
        remaining -= weight

        def minimum_energy(start):
            closest = min(max(target, start), start + remaining)
            return (closest - target) ** 2

        if minimum_energy(packs + weight) < minimum_energy(packs):
            packs += weight
    return packs


def evaluate(plan, recorded_price):
    if plan.reserved > plan.on_hand:
        raise HTTPException(422, "Reserved units exceed stock on hand.")
    opening = plan.on_hand - plan.reserved
    if plan.inbound_units and (plan.inbound_date is None or plan.inbound_date < plan.start):
        raise HTTPException(422, "Enter the expected arrival date for the firm inbound.")
    # Size against each day's unmet demand. A later receipt cannot cover an earlier shortage.
    baseline = []
    stock = opening
    gap = 0
    for offset in range(7):
        when = plan.start + timedelta(days=offset)
        firm = plan.inbound_units if when == plan.inbound_date else 0
        stock += firm
        shortage = max(0, plan.daily_demand - stock)
        stock = max(0, stock - plan.daily_demand)
        baseline.append((firm, stock, shortage))
        if offset >= plan.lead_days:
            gap += shortage
    rate = Decimal(plan.landed_unit_paise) if plan.landed_unit_paise else recorded_price * 100
    min_packs = int((plan.minimum_order / plan.pack).to_integral_value(rounding=ROUND_CEILING))
    target_packs = max(min_packs, int((gap / plan.pack).to_integral_value(rounding=ROUND_CEILING))) if gap else 0

    def cost(packs):
        return int((packs * plan.pack * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    reasons = []
    # ROUND_HALF_UP makes a positive total affordable exactly when the
    # unrounded cost is strictly less than budget + half a paise.
    numerator, denominator = (plan.pack * rate).as_integer_ratio()
    capacity = ((2 * plan.spendable_paise + 1) * denominator - 1) // (2 * numerator)
    packs = solve_pack_qubo(target_packs, min_packs, capacity)
    if target_packs and plan.quote_expiry and plan.quote_expiry < plan.start:
        reasons.append(f"Quote expired on {plan.quote_expiry}.")
        packs = 0
    elif packs < target_packs:
        reasons.append("Available cash covers only part of the demand." if packs else
                       "Available cash cannot fund the minimum pack-rounded order.")
    units = packs * plan.pack
    spend = cost(packs)
    stock = opening
    days = []
    for offset in range(7):
        firm, no_order_stock, no_order_shortage = baseline[offset]
        incoming = firm + (units if offset == plan.lead_days else 0)
        stock += incoming
        missed = max(0, plan.daily_demand - stock)
        stock = max(0, stock - plan.daily_demand)
        days.append(dict(date=plan.start + timedelta(days=offset), incoming=incoming,
                         closing=stock, unmet=missed,
                         no_order_closing=no_order_stock, no_order_unmet=no_order_shortage))
    first_miss = next((d for d in days if d["unmet"]), None)
    if first_miss:
        reasons.append(f"First uncovered demand on {first_miss['date']}.")
    covered = sum(d["no_order_unmet"] - d["unmet"] for d in days)
    return dict(units=units, spend_paise=spend, remaining_paise=plan.spendable_paise - spend,
                additional_demand_covered=covered, reasons=reasons, days=days,
                price_basis="confirmed" if plan.landed_unit_paise else "historical")


@router.get("/prices")
def inventory_prices():
    return read_prices()


@router.post("/compare")
def compare_inventory(plan: Plan):
    prices = read_prices(plan.line_id)
    if not prices:
        raise HTTPException(404, "Bill line unavailable.")
    if prices[0]["bill_date"] > plan.start:
        raise HTTPException(422, "Start date precedes the supplier bill.")
    return jsonable_encoder(evaluate(plan, prices[0]["price"]))
