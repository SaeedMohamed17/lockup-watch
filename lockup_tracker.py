"""
IPO Lockup Expiration Tracker — v1
------------------------------------
Pulls recent IPO prospectus filings (Form 424B4) from SEC EDGAR's free,
public full-text search API, then estimates each company's lockup
expiration date (filing date + 180 days, the standard lockup period).
 
Data source: SEC EDGAR Full-Text Search API
  https://efts.sec.gov/LATEST/search-index
  - Free, public, no API key required
  - SEC asks that all requests include a descriptive User-Agent with
    contact info (this is standard SEC.gov API etiquette, not optional)
 
Run:
    pip install requests
    python lockup_tracker.py
"""
 
import re
import requests
import csv
import sqlite3
import time
from datetime import datetime, timedelta, timezone
 
# --- CONFIG -----------------------------------------------------------
 
# SEC requires a descriptive User-Agent identifying you/your app.
# Replace with your own name/email before running for real.
HEADERS = {
    "User-Agent": "LockupTracker research@example.com"
}
 
SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
 
# Standard lockup period assumption (most common in US IPOs)
DEFAULT_LOCKUP_DAYS = 180
 
# How many days back to search for new 424B4 filings
LOOKBACK_DAYS = 365
 
OUTPUT_CSV = "lockup_tracker_output.csv"
DB_FILE = "lockups.db"
 
# Keywords that flag a filer as a SPAC (blank-check company) rather than
# a real operating-company IPO. Not perfect, but catches the vast majority.
SPAC_KEYWORDS = [
    "acquisition corp", "acquisition co", "acquisition i", "acquisition ii",
    "acquisition iii", "acquisition iv", "acquisition v", "blank check",
    "capital partners", "holdings corp", "spac", "merger corp",
]
 
 
# --- CORE FUNCTIONS -----------------------------------------------------
 
def fetch_recent_424b4_filings(lookback_days=LOOKBACK_DAYS):
    """
    Query SEC EDGAR full-text search for recent 424B4 filings
    (final IPO prospectuses). Returns a list of raw filing dicts.
    """
    end_date = datetime.today()
    start_date = end_date - timedelta(days=lookback_days)
 
    params = {
        "q": "\"lock-up\"",       # search term - lockup clauses are always mentioned
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
            break  # last page
 
        frm += page_size
        time.sleep(0.3)  # be polite to SEC's servers
 
    return all_hits
 
 
def clean_company_and_ticker(raw_name):
    """
    EDGAR's display name looks like:
      'Constellation Energy Corp  (CEG)  (CIK 0001868275)'
    Split that into a clean company name and a separate ticker field.
    """
    ticker = None
 
    # Grab the LAST (...) group that isn't the CIK one — that's the ticker.
    # e.g. "Real Messenger Corp  (RMSG, RMSGW)  (CIK 0001983324)" -> "RMSG, RMSGW"
    matches = re.findall(r"\(([^()]+)\)", raw_name)
    for m in matches:
        if not m.strip().upper().startswith("CIK"):
            ticker = m.strip()
 
    # Strip all parenthetical groups to get a clean company name
    company_clean = re.sub(r"\s*\([^()]*\)", "", raw_name).strip()
 
    return company_clean, ticker
 
 
def is_likely_spac(company_name):
    name_lower = company_name.lower()
    return any(keyword in name_lower for keyword in SPAC_KEYWORDS)
 
 
def parse_filing(hit):
    """
    Extract the fields we care about from one raw EDGAR search hit.
    """
    source = hit.get("_source", {})
 
    company_names = source.get("display_names", ["Unknown"])
    raw_name = company_names[0] if company_names else "Unknown"
    company_clean, ticker = clean_company_and_ticker(raw_name)
 
    filed_at = source.get("file_date")  # format: YYYY-MM-DD
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
    """
    Some companies file more than one 424B4 (amended versions, multiple
    share classes, etc). Keep only the EARLIEST filing per CIK, since
    that's the one that actually starts the lockup clock.
    """
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
    """
    Upsert rows into SQLite, keyed on CIK. Running this daily just adds
    new IPOs and leaves existing ones alone (their lockup date doesn't
    change once it's calculated).
    """
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
 
    # Sort soonest-expiring first
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