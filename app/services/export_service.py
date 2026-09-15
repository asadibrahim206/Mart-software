"""
Generic CSV export — spec section 44 ("export reports to CSV, Excel, PDF"). This phase
implements CSV (the universal, dependency-free format); Excel/PDF export can reuse this same
row-building pattern later with a different renderer.

Usage pattern: a list endpoint accepts `export: Literal["csv"] | None = None`; when set, it
builds the same rows it would have returned as JSON and calls `rows_to_csv_response()` instead
of returning the Page/list normally.
"""
import csv
import io
from typing import Any

from fastapi.responses import StreamingResponse


def rows_to_csv_response(rows: list[dict[str, Any]], filename: str) -> StreamingResponse:
    buffer = io.StringIO()
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    else:
        buffer.write("")  # empty export — still a valid, openable CSV with no rows

    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
