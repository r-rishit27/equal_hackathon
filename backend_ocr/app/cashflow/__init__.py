"""Cash Flow Forecast (docs/cashflow-forecast/).

Read-only towards the books: this package reads payables, payouts, receivables
and bank balances, and writes only its own cf_* tables (plus the forecast
columns of fact_cashflow_daily). Money is integer paise throughout.
"""
