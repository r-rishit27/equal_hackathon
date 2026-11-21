"""Temporary document evidence. All arithmetic is performed with Decimal."""
import csv
import io
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from fastapi import HTTPException


def number(value):
    try:
        n = Decimal((value or "").strip().replace(",", ""))
        if not n.is_finite() or abs(n) > 10**12 or n.as_tuple().exponent < -8:
            raise ValueError()
        return n
    except (InvalidOperation, ValueError, AttributeError):
        raise HTTPException(422, "A numeric column contains an invalid amount.")


def inspect_document(filename, data):
    if not data or len(data)>2*1024*1024:
        raise HTTPException(413, "Choose a nonempty file of up to 2 MB.")
    ext = Path(filename).suffix.lower()
    if ext==".pdf":
        import pymupdf
        try:
            with pymupdf.open(stream=data,filetype="pdf") as doc:
                if doc.needs_pass or len(doc)>12:
                    raise HTTPException(422,"Use an unlocked PDF of up to 12 pages.")
                text = "".join(page.get_text()[:4000] for page in doc)[:12000]
        except (RuntimeError, ValueError):
            raise HTTPException(422,"The PDF could not be read.")
        if not text.strip():
            raise HTTPException(422,"This PDF has no readable text. Upload a text PDF or CSV.")
        return dict(title=Path(filename).name[:120],excerpt=text)
    if ext not in {".csv",".txt"}:
        raise HTTPException(415,"Supported files are PDF, UTF-8 CSV, and TXT.")
    try:
        text=data.decode("utf-8-sig")
    except UnicodeError:
        raise HTTPException(422,"Use UTF-8 encoding.")
    result=dict(title=Path(filename).name[:120],excerpt=text[:12000])
    if ext!=".csv":
        return result
    reader=csv.DictReader(io.StringIO(text))
    reader.fieldnames=[s.strip().lower() for s in reader.fieldnames or []]
    arithmetic={"quantity","unit_price","line_total"} <= set(reader.fieldnames)
    invoice_refs={"invoice_number","invoice_total","currency"} <= set(reader.fieldnames)
    if not (arithmetic or invoice_refs):
        return result
    mismatches=[]
    checked=0
    claims={}
    try:
        for i,row in enumerate(reader,2):
            if i>2001:
                raise HTTPException(422,"Use at most 2,000 CSV rows.")
            if arithmetic:
                total=(number(row["quantity"])*number(row["unit_price"])).quantize(Decimal(".01"),rounding=ROUND_HALF_UP)
                diff=number(row["line_total"])-total
                if diff:
                    mismatches.append(dict(row=i,expected=str(total),difference=str(diff)))
                checked+=1
            if invoice_refs:
                ref=(row.get("invoice_number") or "").strip()
                currency=(row.get("currency") or "").strip().upper()
                if not ref or len(ref)>100 or len(currency)!=3:
                    raise HTTPException(422,"Supply an invoice number and three-letter currency for reconciliation.")
                amount=number(row["invoice_total"])
                if ref in claims and claims[ref]!=(currency,amount):
                    raise HTTPException(422,"The same invoice has conflicting currency or totals.")
                claims[ref]=(currency,amount)
                if len(claims)>8:
                    raise HTTPException(422,"Compare up to eight distinct invoices per file.")
    except csv.Error:
        raise HTTPException(422,"Invalid CSV.")
    if arithmetic:
        result.update(checked_rows=checked,mismatch_count=len(mismatches),examples=mismatches[:20],
                      formula="quantity multiplied by unit_price, before tax and discounts")
    if claims:
        result["invoice_claims"]=[dict(number=k,currency=v[0],total=str(v[1])) for k,v in claims.items()]
    return result
