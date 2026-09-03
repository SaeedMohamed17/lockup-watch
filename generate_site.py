# Reads lockups.db and builds index.html
# Run after lockup_tracker.py


import sqlite3
from datetime import datetime, date, timezone
 
DB_FILE = "lockups.db"
OUTPUT_HTML = "index.html"
 
 
def fetch_rows(db_file=DB_FILE):
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT company, ticker, is_spac, filed_date, cik, accession_no,
               estimated_lockup_expiration, lockup_days_assumed
        FROM lockups
        ORDER BY estimated_lockup_expiration ASC
    """).fetchall()
    conn.close()
    return rows
 
 
def days_until(date_str):
    if not date_str:
        return None
    try:
        target = datetime.strptime(date_str, "%Y-%m-%d").date()
        return (target - date.today()).days
    except ValueError:
        return None
 
 
def edgar_filing_url(cik, accession_no):
    # link straight to the filing on EDGAR using CIK + accession number
    if not cik or not accession_no:
        return None
    acc_nodash = accession_no.replace("-", "")
    cik_int = str(int(cik))  # strip leading zeros
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/"
 
 
def build_row_html(row, idx):
    ticker = row["ticker"].split(",")[0].strip() if row["ticker"] else "—"
    company = row["company"]
    filed = row["filed_date"] or "—"
    expiry = row["estimated_lockup_expiration"] or "—"
    spac_tag = ' <span class="tag">SPAC</span>' if row["is_spac"] else ""
 
    filing_url = edgar_filing_url(row["cik"], row["accession_no"])
    link_open = f'<a href="{filing_url}" target="_blank" rel="noopener">' if filing_url else "<span>"
    link_close = "</a>" if filing_url else "</span>"
 
    d = days_until(row["estimated_lockup_expiration"])
    if d is None:
        countdown, cclass = "—", ""
    elif d < 0:
        countdown, cclass = "expired", "neg"
    elif d <= 14:
        countdown, cclass = f"{d}d", "soon"
    else:
        countdown, cclass = f"{d}d", ""
 
    row_class = "row"
    if cclass == "soon":
        row_class += " row-soon"
 
    return f"""    <tr class="{row_class}" data-spac="{1 if row['is_spac'] else 0}" data-days="{d if d is not None else ''}">
      <td class="num">{idx}</td>
      <td class="date">{filed}</td>
      <td class="ticker">{link_open}{ticker}{link_close}</td>
      <td class="company">{link_open}{company}{link_close}{spac_tag}</td>
      <td class="date">{expiry}</td>
      <td class="lockup-len">{row['lockup_days_assumed']}d</td>
      <td class="countdown {cclass}">{countdown}</td>
    </tr>"""
 
 
def generate_html(rows):
    total = len(rows)
    real_count = sum(1 for r in rows if not r["is_spac"])
    spac_count = total - real_count
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
 
    rows_html = "\n".join(build_row_html(r, i + 1) for i, r in enumerate(rows))
 
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Lockup Watch - IPO Lockup Expiration Screener</title>
<style>
  body {{
    margin: 0;
    padding: 0;
    background: #ffffff;
    color: #000000;
    font-family: Arial, Helvetica, sans-serif;
    font-size: 11px;
  }}
  a {{
    color: #0000EE;
    text-decoration: none;
  }}
  a:hover {{ text-decoration: underline; }}
 
  #topnav {{
    background: #f0f0f0;
    border-bottom: 1px solid #999;
    padding: 3px 8px;
    font-size: 11px;
  }}
  #topnav a {{
    margin-right: 14px;
    color: #0000EE;
  }}
  #topnav .brand {{
    font-weight: bold;
    color: #000;
    margin-right: 20px;
    font-size: 13px;
  }}
 
  h1 {{
    font-size: 14px;
    margin: 6px 8px 1px 8px;
  }}
  .subtitle {{
    margin: 0 8px 4px 8px;
    color: #444;
    font-size: 11px;
  }}
  .stats-bar {{
    margin: 0 8px 4px 8px;
    font-size: 11px;
    color: #333;
  }}
  .stats-bar b {{ color: #000; }}
 
  table {{
    border-collapse: collapse;
    width: 100%;
    margin: 0 0 20px 0;
    table-layout: fixed;
  }}
  th {{
    background: #d9d9d9;
    border: 1px solid #999;
    padding: 3px 6px;
    text-align: left;
    font-size: 11px;
    font-weight: bold;
    white-space: nowrap;
  }}
  td {{
    border: 1px solid #ccc;
    padding: 3px 6px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  tr:nth-child(even) td {{
    background: #f5f5f5;
  }}
  tr:hover td {{
    background: #ffffcc;
  }}
  tr.row-soon td {{
    background: #ffe0e0;
  }}
  tr.row-soon:hover td {{
    background: #ffc9c9;
  }}
 
  th:nth-child(1), td.num {{ width: 3%; }}
  th:nth-child(2), td.date:nth-of-type(1) {{ width: 10%; }}
  th:nth-child(3), td.ticker {{ width: 8%; }}
  th:nth-child(4), td.company {{ width: 44%; }}
  th:nth-child(5) {{ width: 12%; }}
  th:nth-child(6), td.lockup-len {{ width: 8%; }}
  th:nth-child(7), td.countdown {{ width: 8%; }}
 
  td.num {{ color: #888; text-align: right; }}
  td.date {{ font-family: Consolas, monospace; }}
  td.ticker {{ font-weight: bold; }}
  td.company {{ white-space: normal; overflow: visible; }}
  td.lockup-len {{ text-align: right; color: #555; }}
  td.countdown {{ text-align: right; font-weight: bold; }}
  td.countdown.soon {{ color: #a00; }}
  td.countdown.neg {{ color: #888; font-weight: normal; }}
 
  .tag {{
    font-size: 9px;
    font-weight: bold;
    color: #888;
    border: 1px solid #ccc;
    padding: 0 3px;
  }}
 
  #topnav a.active {{
    font-weight: bold;
    text-decoration: underline;
    color: #000;
  }}
 
  #result-count {{
    margin: 0 8px 4px 8px;
    font-size: 11px;
    color: #555;
  }}
 
  #search-box {{
    margin: 0 8px 6px 8px;
  }}
  #search-input {{
    font-family: Arial, Helvetica, sans-serif;
    font-size: 11px;
    padding: 3px 6px;
    border: 1px solid #999;
    width: 240px;
  }}
 
  th.sortable::after {{
    content: " \\21C5";
    color: #999;
    font-size: 9px;
  }}
 
  footer {{
    margin: 10px 8px 30px 8px;
    font-size: 10px;
    color: #777;
  }}
</style>
</head>
<body>
 
<div id="topnav">
  <span class="brand">Lockup Watch</span>
  <a href="#" onclick="filterRows('all'); return false;" id="nav-all">All IPOs</a>
  <a href="#" onclick="filterRows('real'); return false;" id="nav-real">Operating Companies Only</a>
  <a href="#" onclick="filterRows('spac'); return false;" id="nav-spac">SPACs Only</a>
  <a href="#" onclick="filterRows('week'); return false;" id="nav-week">Expiring This Week</a>
  <a href="#" onclick="filterRows('month'); return false;" id="nav-month">Expiring This Month</a>
</div>
 
<h1>IPO Lockup Expiration Screener</h1>
<div class="subtitle">Tracks Form 424B4 IPO prospectus filings from SEC EDGAR and estimates each company's insider lockup expiration date.</div>
 
<div class="stats-bar">
  <b>{total}</b> filings tracked &nbsp;|&nbsp;
  <b>{real_count}</b> operating companies &nbsp;|&nbsp;
  <b>{spac_count}</b> SPACs &nbsp;|&nbsp;
  updated <b>{generated_at}</b>
</div>
 
<div id="search-box">
  <input type="text" id="search-input" placeholder="Search ticker or company..." onkeyup="applySearch()">
</div>
 
<div id="result-count"></div>
 
<table>
  <thead>
    <tr>
      <th class="sortable" onclick="sortTable(0, this)">#</th>
      <th class="sortable" onclick="sortTable(1, this)">Filed</th>
      <th class="sortable" onclick="sortTable(2, this)">Ticker</th>
      <th class="sortable" onclick="sortTable(3, this)">Company Name</th>
      <th class="sortable" onclick="sortTable(4, this)">Est. Lockup Expiry</th>
      <th class="sortable" onclick="sortTable(5, this)">Lockup Len</th>
      <th class="sortable" onclick="sortTable(6, this)">Countdown</th>
    </tr>
  </thead>
  <tbody>
{rows_html}
  </tbody>
</table>
 
<footer>
  Data source: SEC EDGAR full-text search (Form 424B4 filings). Lockup dates are estimates
  (filing date + assumed lockup length) and may not reflect actual terms such as early-release
  clauses. Not investment advice.
</footer>
 
<script>
  let currentMode = "all";
 
  function filterRows(mode) {{
    currentMode = mode;
    document.querySelectorAll("#topnav a").forEach(a => a.classList.remove("active"));
    document.getElementById("nav-" + mode).classList.add("active");
    applySearch();
  }}
 
  function applySearch() {{
    const rows = document.querySelectorAll("tbody tr.row");
    const query = document.getElementById("search-input").value.trim().toLowerCase();
    let shown = 0;
 
    rows.forEach(row => {{
      const isSpac = row.dataset.spac === "1";
      const days = row.dataset.days === "" ? null : parseInt(row.dataset.days, 10);
      let visible = true;
 
      if (currentMode === "real") visible = !isSpac;
      else if (currentMode === "spac") visible = isSpac;
      else if (currentMode === "week") visible = days !== null && days >= 0 && days <= 7;
      else if (currentMode === "month") visible = days !== null && days >= 0 && days <= 30;
 
      if (visible && query) {{
        const ticker = row.cells[2].innerText.toLowerCase();
        const company = row.cells[3].innerText.toLowerCase();
        visible = ticker.includes(query) || company.includes(query);
      }}
 
      row.style.display = visible ? "" : "none";
      if (visible) shown++;
    }});
 
    document.getElementById("result-count").textContent =
      "Showing " + shown + " of " + rows.length + " filings";
  }}
 
  function sortTable(colIndex, headerEl) {{
    const table = headerEl.closest("table");
    const tbody = table.tBodies[0];
    const rows = Array.from(tbody.querySelectorAll("tr.row"));
    const asc = table.dataset.sortCol == colIndex && table.dataset.sortDir !== "asc";
 
    rows.sort((a, b) => {{
      const av = a.cells[colIndex].innerText.trim();
      const bv = b.cells[colIndex].innerText.trim();
      return asc ? av.localeCompare(bv, undefined, {{numeric: true}})
                 : bv.localeCompare(av, undefined, {{numeric: true}});
    }});
 
    rows.forEach(r => tbody.appendChild(r));
    table.dataset.sortCol = colIndex;
    table.dataset.sortDir = asc ? "asc" : "desc";
  }}
 
  filterRows("all");
</script>
 
</body>
</html>
"""
 
 
def is_expired(date_str):
    d = days_until(date_str)
    return d is not None and d < 0
 
 
def main():
    all_rows = fetch_rows()
    if not all_rows:
        print("No data in database yet - run lockup_tracker.py first.")
        return
 
    active_rows = [r for r in all_rows if not is_expired(r["estimated_lockup_expiration"])]
    expired_count = len(all_rows) - len(active_rows)
 
    html = generate_html(active_rows)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
 
    print(f"Generated {OUTPUT_HTML} with {len(active_rows)} active rows "
          f"({expired_count} expired filings excluded).")
 
 
if __name__ == "__main__":
    main()
