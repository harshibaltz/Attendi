"""CSV download helper.

CSV is not JSON, so these responses deliberately bypass the DRF envelope
renderer: a plain ``HttpResponse`` is returned as-is.
"""
import csv

from django.http import HttpResponse

# Cells that begin with one of these characters can be interpreted as a
# formula by Excel/Sheets when the file is opened. Prefixing with an
# apostrophe keeps the text literal.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _safe(value):
    if value is None:
        return ""
    text = str(value)
    if text.startswith(_FORMULA_PREFIXES):
        return f"'{text}"
    return text


def csv_response(filename, header, rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    # BOM so Excel opens accented names correctly instead of mojibake.
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_safe(value) for value in row])
    return response
