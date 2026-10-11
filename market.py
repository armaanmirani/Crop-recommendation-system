"""Official Agmarknet/data.gov.in price adapter; never substitutes demo prices."""
import csv
from datetime import date, datetime, timezone
import io
import json
import math
import os
import re
import secrets
import threading
import time
from collections import OrderedDict
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import build_opener, HTTPRedirectHandler, Request

RESOURCE_ID = "9ef84268-d588-465a-a308-a864a43d0070"
API_URL = f"https://api.data.gov.in/resource/{RESOURCE_ID}"
SOURCE_URL = "https://www.data.gov.in/resource/current-daily-price-various-commodities-various-markets-mandi"
PORTAL_URL = "https://agmarknet.gov.in/"
# Exact commodity-name suggestions. The chosen sale form must match expected yield.
COMMODITIES = {
    "rice": ["Paddy(Dhan)(Common)", "Paddy(Dhan)(Basmati)", "Rice"],
    "maize": ["Maize"], "chickpea": ["Bengal Gram(Gram)(Whole)"],
    "kidneybeans": ["Rajma"], "pigeonpeas": ["Arhar (Tur/Red Gram)(Whole)"],
    "mothbeans": ["Moth"], "mungbean": ["Green Gram (Moong)(Whole)"],
    "blackgram": ["Black Gram (Urd Beans)(Whole)"], "lentil": ["Lentil (Masur)(Whole)"],
    "pomegranate": ["Pomegranate"], "banana": ["Banana"], "mango": ["Mango"],
    "grapes": ["Grapes"], "watermelon": ["Water Melon"], "muskmelon": ["Musk Melon"],
    "apple": ["Apple"], "orange": ["Orange"], "papaya": ["Papaya"],
    "coconut": ["Coconut"], "cotton": ["Cotton"], "jute": ["Jute"], "coffee": ["Coffee"],
}
QUOTES = OrderedDict()
QUOTE_LOCK = threading.RLock()
QUOTE_TTL = 3600
STALE_DAYS = 7


class MarketError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward the API key to another endpoint.


def today():
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


def text(value, name, required=False):
    if not isinstance(value, str) or len(value) > 100 or any(ord(ch) < 32 for ch in value):
        raise ValueError(f"{name} must be text of at most 100 characters.")
    result = value.strip()
    if required and not result:
        raise ValueError(f"Enter {name}.")
    return result


def filters(values):
    crop = text(values.get("crop", ""), "crop", True)
    if crop not in COMMODITIES:
        raise ValueError("Choose a supported crop.")
    commodity = text(values.get("commodity", COMMODITIES[crop][0]), "commodity", True)
    if commodity not in COMMODITIES[crop]:
        raise ValueError("Choose one of this crop's supported sale commodities.")
    result = {"crop": crop, "commodity": commodity, "state": text(values.get("state", ""), "state", True)}
    for name in ("district", "market"):
        result[name] = text(values.get(name, ""), name)
    requested_date = text(values.get("date", ""), "date")
    if requested_date:
        try:
            parsed = date.fromisoformat(requested_date)
        except ValueError:
            raise ValueError("Date must use YYYY-MM-DD.") from None
        if parsed > today():
            raise ValueError("Price-report date cannot be in the future.")
    result["date"] = requested_date
    return result


def normalized(value):
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def column_name(value):
    key = normalized(value)
    aliases = {"statename":"state", "districtname":"district", "marketname":"market", "commodityname":"commodity"}
    for price in ("minprice", "maxprice", "modalprice"):
        for suffix in ("rsquintal", "rsqtl", "inrquintal"):
            aliases[price + suffix] = price
    return aliases.get(key, key)


def parse_date(value):
    for pattern in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y"):
        try:
            return datetime.strptime(str(value).strip(), pattern).date()
        except ValueError:
            pass
    raise ValueError("Unrecognized price date.")


def parse_record(row, selected, source, unit="INR/quintal", csv_export=False):
    if not isinstance(row, dict):
        raise ValueError("Invalid record.")
    fields = {column_name(k): v for k, v in row.items() if k is not None}
    supplied_state = csv_export and not fields.get("state")
    if supplied_state:
        fields["state"] = selected["state"]
    commodity = str(fields.get("commodity", "")).strip()
    if normalized(commodity) != normalized(selected["commodity"]):
        return None
    for name in ("state", "district", "market"):
        if selected[name] and normalized(fields.get(name, "")) != normalized(selected[name]):
            return None
        if not fields.get(name):
            raise ValueError("Missing market location.")
    reported = parse_date(fields.get("arrivaldate", fields.get("pricedate", "")))
    if reported > today():
        raise ValueError("Future-dated report.")
    if selected["date"] and reported.isoformat() != selected["date"]:
        return None
    provided_unit = fields.get("unit", fields.get("priceunit", ""))
    if provided_unit and normalized(provided_unit) not in {
        "inrquintal", "rsquintal", "rsqtl", "rupeesquintal", "quintal", "qtl"
    }:
        raise ValueError("Unsupported price unit; conversion to kg is not established.")
    if selected["crop"] == "coconut":
        # Coconut reports may be per piece or per thousand nuts: no silent kg conversion.
        raise ValueError("Coconut's weight unit must be independently verified before importing a kg price.")
    prices = {}
    for field in ("minprice", "maxprice", "modalprice"):
        value = fields.get(field)
        if isinstance(value, bool):
            raise ValueError("Invalid price.")
        price = float(str(value).replace(",", ""))
        if not math.isfinite(price) or not 0 < price <= 100000000:
            raise ValueError("Invalid price.")
        prices[field] = price
    if not prices["minprice"] <= prices["modalprice"] <= prices["maxprice"]:
        raise ValueError("Inconsistent min/modal/max prices.")
    age = (today() - reported).days
    return {
        "crop": selected["crop"], "commodity": commodity,
        "state": str(fields["state"]), "district": str(fields["district"]), "market": str(fields["market"]),
        "variety": str(fields.get("variety", "Not specified")), "grade": str(fields.get("grade", "Not specified")),
        "report_date": reported.isoformat(), "age_days": age, "stale": age > STALE_DAYS,
        "min_price": prices["minprice"], "max_price": prices["maxprice"], "modal_price": prices["modalprice"],
        "original_unit": unit, "price_per_kg": prices["modalprice"] / 100,
        "conversion": "1 quintal = 100 kg; modal price divided by 100.",
        "source": source, "source_url": SOURCE_URL if source.startswith("Agmarknet via") else PORTAL_URL,
        "state_from_export_filter": bool(supplied_state),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }


def register(record):
    token = secrets.token_urlsafe(24)
    with QUOTE_LOCK:
        expired = [key for key, (created, _) in QUOTES.items() if time.monotonic() - created > QUOTE_TTL]
        for key in expired:
            del QUOTES[key]
        while len(QUOTES) >= 2000:
            QUOTES.popitem(last=False)
        QUOTES[token] = (time.monotonic(), dict(record))
    return {**record, "quote_id": token}


def resolve_quote(token, crop):
    if not isinstance(token, str) or len(token) > 100:
        raise ValueError("Invalid market quote reference.")
    with QUOTE_LOCK:
        entry = QUOTES.get(token)
    if entry is None or time.monotonic() - entry[0] > QUOTE_TTL:
        raise ValueError("Market quote expired or the server restarted. Fetch/import the price again.")
    record = entry[1]
    if record["crop"] != crop:
        raise ValueError("Market quote does not belong to this crop.")
    if (today() - date.fromisoformat(record["report_date"])).days > STALE_DAYS:
        raise ValueError("Market quote is over 7 days old. Fetch a more recent report or enter an explicitly manual estimate.")
    return dict(record)


def results(rows, selected, source, total=None, offset=0, csv_export=False):
    records, invalid = [], 0
    for row in rows:
        try:
            record = parse_record(row, selected, source, csv_export=csv_export)
            if record:
                records.append(record)
        except (ValueError, TypeError, OverflowError):
            invalid += 1
    records.sort(key=lambda record: (record["report_date"], record["market"], record["variety"]), reverse=True)
    unique = {}
    for record in records:
        identity = tuple(record[field] for field in ("commodity", "state", "district", "market", "variety", "grade", "report_date", "modal_price"))
        unique[identity] = record
    warnings = []
    if invalid:
        warnings.append(f"Skipped {invalid} records with invalid dates, prices, locations, or unsupported units.")
    if any(record["state_from_export_filter"] for record in unique.values()):
        warnings.append("The CSV omits State; its state comes from your selected export filter. Confirm that the file was exported for that state.")
    if selected["crop"] == "coconut":
        warnings.append("Coconut prices may be reported per nut, not per quintal. Automatic kg conversion is disabled; confirm the unit and weight before entering a manual price.")
    if any(record["stale"] for record in unique.values()):
        warnings.append("Some reports are over 7 days old and cannot be used for automatic price filling.")
    if not unique:
        warnings.append("No matching usable reports. Check the exact state, district, mandi, commodity, and report date.")
    if total is not None and offset + len(rows) < total:
        warnings.append("More reports are available. This page is not an exhaustive latest-price search; narrow your filters or load another page.")
    return {"records": [register(record) for record in unique.values()], "filters": selected,
            "warnings": warnings, "source": source, "total": total, "offset": offset,
            "next_offset": offset + len(rows) if total is not None and rows and offset + len(rows) < total else None,
            "freshness_limit_days": STALE_DAYS}


def fetch_prices(values):
    selected = filters(values)
    try:
        offset = int(values.get("offset", 0))
    except (ValueError, TypeError):
        raise ValueError("Invalid page offset.") from None
    if not 0 <= offset <= 10000:
        raise ValueError("Narrow your filters; the maximum page offset is 10000.")
    key = os.environ.get("DATA_GOV_API_KEY", "")
    if not key:
        raise MarketError("Live lookup needs a data.gov.in API key configured on the server. You can still import an official CSV export or enter a manual estimate.", 503)
    params = {"api-key": key, "format": "json", "limit": "100", "offset": str(offset)}
    for name in ("state", "district", "market", "commodity"):
        if selected[name]:
            params[f"filters[{name}]"] = selected[name]
    if selected["date"]:
        params["filters[arrival_date]"] = date.fromisoformat(selected["date"]).strftime("%d/%m/%Y")
    req = Request(API_URL + "?" + urlencode(params), headers={"Accept": "application/json", "User-Agent": "TerraCropPlanner/1.0"})
    try:
        with build_opener(NoRedirect()).open(req, timeout=15) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise MarketError("The market service returned too much data. Narrow your location filters.")
        payload = json.loads(raw)
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise MarketError("The market service denied access. Check the configured API key and network access.", 503) from None
        if exc.code == 429:
            raise MarketError("The market service rate limit was reached. Try again later.", 429) from None
        raise MarketError("The market service is unavailable. Try later or import an official CSV export.") from None
    except (URLError, TimeoutError, OSError):
        raise MarketError("Cannot reach data.gov.in. Check network access or import an official CSV export.", 503) from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise MarketError("The market service returned an unreadable response.") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list) or str(payload.get("status", "")).lower() in ("error", "failed", "fail"):
        raise MarketError("The market service did not return price records. Check API authorization and resource availability.")
    try:
        total = int(payload.get("total", len(payload["records"])))
        if total < 0:
            raise ValueError("Negative total")
    except (TypeError, ValueError):
        raise MarketError("The market service returned an invalid record count.") from None
    return results(payload["records"], selected, "Agmarknet via data.gov.in API", total, offset)


def import_csv(raw, values):
    selected = filters(values)
    portal = values.get("portal", "agmarknet")
    if portal not in ("agmarknet", "data_gov"):
        raise ValueError("Choose Agmarknet or data.gov.in as the export source.")
    if values.get("confirmed_unit") != "INR/quintal":
        raise ValueError("Confirm the official export's price unit is INR/quintal before importing.")
    try:
        decoded = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(decoded))
        columns = {column_name(name) for name in (reader.fieldnames or [])}
        if not {"district", "market", "commodity", "minprice", "maxprice", "modalprice"}.issubset(columns) or not columns.intersection({"arrivaldate", "pricedate"}):
            raise ValueError("CSV needs District, Market, Commodity, Min Price, Max Price, Modal Price, and Arrival Date (or Price Date). State is optional for a state-specific export.")
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error):
        raise ValueError("Use a UTF-8 CSV export from Agmarknet or data.gov.in.") from None
    if len(rows) > 5000:
        raise ValueError("CSV exceeds 5000 rows. Export a narrower location or date range.")
    source = "Agmarknet portal CSV (user-supplied)" if portal == "agmarknet" else "Agmarknet via data.gov.in CSV (user-supplied)"
    return results(rows, selected, source, csv_export=True)
