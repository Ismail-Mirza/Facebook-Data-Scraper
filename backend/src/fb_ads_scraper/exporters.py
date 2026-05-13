from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Iterator
from pathlib import Path

from fb_ads_scraper.models import Ad

CSV_COLUMNS = [
    "ad_archive_id",
    "page_id",
    "page_name",
    "start_date",
    "end_date",
    "is_active",
    "publisher_platforms",
    "body_text",
    "cta_text",
    "cta_type",
    "display_format",
    "images",
    "videos",
    "landing_url",
    "spend",
    "impressions",
    "currency",
    "funded_by",
    "eu_total_reach",
]


def _row(ad: Ad) -> dict[str, str]:
    d = ad.model_dump(mode="json")
    out: dict[str, str] = {}
    for col in CSV_COLUMNS:
        v = d.get(col)
        if isinstance(v, (list, dict)):
            out[col] = json.dumps(v, ensure_ascii=False)
        elif v is None:
            out[col] = ""
        else:
            out[col] = str(v)
    return out


def write_csv(ads: Iterable[Ad], path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for ad in ads:
            writer.writerow(_row(ad))
    return path


def write_json(ads: Iterable[Ad], path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [ad.model_dump(mode="json", exclude={"raw"}) for ad in ads]
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def stream_csv(ads: Iterable[Ad]) -> Iterator[str]:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    yield buf.getvalue()
    for ad in ads:
        buf.seek(0)
        buf.truncate()
        writer.writerow(_row(ad))
        yield buf.getvalue()


def stream_json(ads: Iterable[Ad]) -> Iterator[str]:
    yield "[\n"
    first = True
    for ad in ads:
        prefix = "" if first else ",\n"
        first = False
        yield prefix + json.dumps(ad.model_dump(mode="json", exclude={"raw"}), ensure_ascii=False)
    yield "\n]\n"
