# Pulls recent IPO filings (424B4) from SEC EDGAR and estimates lockup expiry dates

import re
import requests
import csv
import sqlite3
import time
from datetime import datetime, timedelta, timezone

# --- CONFIG -----------------------------------------------------------

HEADERS = {
    "User-Agent": "LockupTracker saeed.mohamed@torontomu.ca"
}

SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"

DEFAULT_LOCKUP_DAYS = 180
LOOKBACK_DAYS = 365

OUTPUT_CSV = "lockup_tracker_output.csv"
DB_FILE = "lockups.db"

SPAC_KEYWORDS = [
    "acquisition corp", "acquisition co", "acquisition i", "acquisition ii",
    "acquisition iii", "acquisition iv", "acquisition v", "blank check",
    "capital partners", "holdings corp", "spac", "merger corp",
]


# --- CORE FUNCTIONS -----------------------------------------------------

def fetch_recent_424b4_filings(lookback_days=LOOKBACK_DAYS):
    end_date = datetime.today()
    start_date = end_date - timedelta(days=lookback_days)

    params = {
        "q": "\"lock-up\"",
        "forms": "424B4",
        "dateRange": "custom",
        "startdt": start_date.strftime("%Y-%m-%d"),
        "enddt": end_date.strftime("%Y-%m-%d"),
    }

    all_hits = []
    frm = 0
    page_size = 100

    while True:
        params["from"] = frm
        resp = requests.get(SEARCH_URL, headers=HEADERS, params=params, timeout=30)

        if resp.status_code != 200:
            print(f"ERROR: SEC API returned status {resp.status_code}")
            print(resp.text[:500])
            break

        data = resp.json()
        hits = data.get("hits", {}).get("hits", [])

        if not hits:
            break

        all_hits.extend(hits)
        print(f"  fetched {len(hits)} filings (total so far: {len(all_hits)})")

        if len(hits) < page_size:
            break

        frm += page_size
        time.sleep(0.3)

    return all_hits


def clean_company_and_ticker(raw_name):
    ticker = None

    matches = re.findall(r"\(([^()]+)\)", raw_name)
    for m in matches:
        if not m.strip().upper().startswith("CIK"):
            ticker = m.strip()

    company_clean = re.sub(r"\s*\([^()]*\)", "", raw_name).strip()

    return company_clean, ticker


def is_likely_spac(company_name):
    name_lower = company_name.lower()
    return any(keyword in name_lower for keyword in SPAC_KEYWORDS)


def parse_filing(hit):
    source = hit.get("_source", {})

    company_names = source.get("display_names", ["Unknown"])
    raw_name = company_names[0] if company_names else "Unknown"
    company_clean, ticker = clean_company_and_ticker(raw_name)

    filed_at = source.get("file_date")
    form_type = source.get("form")
    cik = source.get("ciks", [None])[0]

    accession_no = hit.get("_id", "").split(":")[0]

    lockup_expiration = None
    if filed_at:
        try:
            filed_date_obj = datetime.strptime(filed_at, "%Y-%m-%d")
            lockup_expiration = (
                filed_date_obj + timedelta(days=DEFAULT_LOCKUP_DAYS)
            ).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return {
        "company": company_clean,
        "ticker": ticker,
        "cik": cik,
        "is_spac": is_likely_spac(company_clean),
        "form_type": form_type,
        "filed_date": filed_at,
        "accession_no": accession_no,
        "estimated_lockup_expiration": lockup_expiration,
        "lockup_days_assumed": DEFAULT_LOCKUP_DAYS,
    }


def dedupe_rows(rows):
    best_by_cik = {}
    for row in rows:
        cik = row["cik"]
        if cik not in best_by_cik:
            best_by_cik[cik] = row
        else:
            existing = best_by_cik[cik]
            if (row["filed_date"] or "9999") < (existing["filed_date"] or "9999"):
                best_by_cik[cik] = row
    return list(best_by_cik.values())


def init_db(db_file=DB_FILE):
    conn = sqlite3.connect(db_file)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lockups (
            cik TEXT PRIMARY KEY,
            company TEXT,
            ticker TEXT,
            is_spac INTEGER,
            form_type TEXT,
            filed_date TEXT,
            accession_no TEXT,
            estimated_lockup_expiration TEXT,
            lockup_days_assumed INTEGER,
            last_updated TEXT
        )
    """)
    conn.commit()
    return conn


def save_to_db(rows, db_file=DB_FILE):
    conn = init_db(db_file)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    for row in rows:
        conn.execute("""
            INSERT INTO lockups
                (cik, company, ticker, is_spac, form_type, filed_date,
                 accession_no, estimated_lockup_expiration,
                 lockup_days_assumed, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cik) DO UPDATE SET
                company=excluded.company,
                ticker=excluded.ticker,
                is_spac=excluded.is_spac,
                form_type=excluded.form_type,
                filed_date=excluded.filed_date,
                accession_no=excluded.accession_no,
                estimated_lockup_expiration=excluded.estimated_lockup_expiration,
                lockup_days_assumed=excluded.lockup_days_assumed,
                last_updated=excluded.last_updated
        """, (
            row["cik"], row["company"], row["ticker"], int(row["is_spac"]),
            row["form_type"], row["filed_date"], row["accession_no"],
            row["estimated_lockup_expiration"], row["lockup_days_assumed"], now
        ))

    conn.commit()
    conn.close()
    print(f"Saved {len(rows)} rows to database ({db_file})")


def save_to_csv(rows, filename=OUTPUT_CSV):
    if not rows:
        print("No rows to save.")
        return

    fieldnames = list(rows[0].keys())
    with open(filename, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nSaved {len(rows)} rows to {filename}")


# --- MAIN ----------------------------------------------------------------

def main():
    print(f"Fetching 424B4 filings from the last {LOOKBACK_DAYS} days...")
    raw_hits = fetch_recent_424b4_filings()

    print(f"\nTotal filings found: {len(raw_hits)}")

    parsed_rows = [parse_filing(hit) for hit in raw_hits]
    parsed_rows = dedupe_rows(parsed_rows)

    parsed_rows.sort(
        key=lambda r: r["estimated_lockup_expiration"] or "9999-99-99"
    )

    real_companies = [r for r in parsed_rows if not r["is_spac"]]
    spacs = [r for r in parsed_rows if r["is_spac"]]

    save_to_csv(parsed_rows, OUTPUT_CSV)
    save_to_csv(real_companies, "lockup_tracker_real_companies_only.csv")
    save_to_db(parsed_rows)

    print(f"\nAfter dedup: {len(parsed_rows)} unique companies")
    print(f"  -> {len(real_companies)} likely real operating companies")
    print(f"  -> {len(spacs)} likely SPACs (flagged, not removed)")

    print("\n--- Preview: real companies, soonest lockup expiry first ---")
    for row in real_companies[:10]:
        ticker_str = f"({row['ticker']})" if row["ticker"] else ""
        print(
            f"{row['company']:<35} {ticker_str:<15} filed {row['filed_date']} "
            f"-> est. lockup expiry {row['estimated_lockup_expiration']}"
        )


if __name__ == "__main__":
    main()
