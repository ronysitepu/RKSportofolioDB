#!/usr/bin/env python3
"""
Generate dashboard-data.json for RKSportofolioDB.
Reads Historical Data and Stock Proportion from Google Sheet via Composio API.
"""

import json, os, re, sys, datetime

SHEET_ID = "1nuM9lZ6fHTHw09KcWIWhXK6uyELS1xtM1QlG-YcLILs"
HOME = os.path.expanduser("~")

def load_creds():
    """Load Composio API key and connectd account ID from config."""
    # API key from config.yaml
    config_path = os.path.join(HOME, ".hermes", "config.yaml")
    api_key = None
    acct_id = None
    with open(config_path) as f:
        for line in f:
            if "x-api-key:" in line:
                api_key = line.split(":", 1)[1].strip()
            if "composio:" in line:
                pass
    # Account ID from user_data or find it
    acct_id = "ca_PK_775oMWhHz"  # Fallback known ID
    return api_key, acct_id
BASE_URL = "https://backend.composio.dev/api/v1"
OUT_DIR = os.path.expanduser("~/RKSportofolioDB")

def run_action(action, body):
    """Call Composio action execute API."""
    import urllib.request
    api_key, acct_id = load_creds()
    url = f"{BASE_URL}/actions/execute"
    payload = {
        "actionName": action,
        "connectedAccountId": acct_id,
        "requestBody": body
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "x-api-key": api_key,
            "Content-Type": "application/json"
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())

def get_sheet_names():
    """Get all sheet names from the spreadsheet."""
    result = run_action("GOOGLESHEETS_GET_SHEET_NAMES", {
        "spreadsheet_id": SHEET_ID
    })
    return result

def batch_get(ranges):
    """Read multiple ranges from the sheet."""
    result = run_action("GOOGLESHEETS_BATCH_GET", {
        "spreadsheet_id": SHEET_ID,
        "ranges": ranges
    })
    return result

def parse_num(v):
    """Parse a number string to float or None."""
    if v is None or v == "":
        return None
    v = v.strip().replace(",", "").replace(" ", "")
    if v == "":
        return None
    try:
        return float(v.replace("%", ""))
    except ValueError:
        return None

def parse_date(d):
    """Parse DD/MM/YYYY or DD/MM/YY to YYYY-MM-DD."""
    if not d or not d.strip():
        return None
    m = re.match(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', d.strip())
    if m:
        day, month, year = m.groups()
        year = int(year)
        if year < 100:
            year += 2000
        return f"{year:04d}-{int(month):02d}-{int(day):02d}"
    return d.strip()

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    
    print("📊 Fetching data from Google Sheet...")
    api_key, acct_id = load_creds()
    if not api_key:
        print("❌ Could not find Composio API key in ~/.hermes/config.yaml")
        sys.exit(1)
    print(f"   Using account: {acct_id}")
    
    # Read both tabs
    result = batch_get([
        "'Historical Data'!A1:O750",
        "'Stock Proportion'!A1:G30"
    ])
    
    # Navigate the response structure
    data = result.get("data", result)
    if "data" in data:
        data = data["data"]
    
    value_ranges = data.get("valueRanges", [])
    if not value_ranges:
        # Try different response structure
        print("Response keys:", list(data.keys()))
        print(json.dumps(data, indent=2)[:1000])
        return
    
    hist_raw = value_ranges[0].get("values", [])
    prop_raw = value_ranges[1].get("values", [])
    
    print(f"   Historical: {len(hist_raw)} rows")
    print(f"   Stock Prop: {len(prop_raw)} rows")
    
    # Parse historical data
    portfolio = []
    for row in hist_raw[1:]:
        if len(row) < 8:
            continue
        date_str = parse_date(row[0]) if len(row) > 0 else None
        if not date_str:
            continue
        
        nab = parse_num(row[4]) if len(row) > 4 else None
        ihsg = parse_num(row[5]) if len(row) > 5 else None
        ret_incep = parse_num(row[8]) if len(row) > 8 else None
        ihsg_incep = parse_num(row[9]) if len(row) > 9 else None
        cagr = parse_num(row[13]) if len(row) > 13 else None
        leverage = parse_num(row[14]) if len(row) > 14 else None
        asset_val = parse_num(row[2]) if len(row) > 2 else None
        ret_weekly = parse_num(row[6]) if len(row) > 6 else None
        ihsg_weekly = parse_num(row[7]) if len(row) > 7 else None
        
        if nab is None and ihsg is None:
            # This row might just have date+week
            continue
        
        entry = {"date": date_str}
        if nab is not None: entry["nab"] = nab
        if ihsg is not None: entry["ihsg"] = ihsg
        if ret_incep is not None: entry["ret_inception"] = ret_incep
        if ihsg_incep is not None: entry["ihsg_inception"] = ihsg_incep
        if cagr is not None: entry["cagr"] = cagr
        if leverage is not None: entry["leverage"] = leverage
        if asset_val is not None: entry["asset_value"] = asset_val
        if ret_weekly is not None: entry["ret_weekly"] = ret_weekly
        if ihsg_weekly is not None: entry["ihsg_ret_weekly"] = ihsg_weekly
        portfolio.append(entry)
    
    if not portfolio:
        print("❌ No data parsed. Check sheet structure.")
        return
    
    print(f"   Parsed {len(portfolio)} data points ({portfolio[0]['date']} to {portfolio[-1]['date']})")
    
    # Parse stocks
    stocks = []
    sectors_sum = {}
    for row in prop_raw[1:]:
        if len(row) < 5:
            continue
        ticker = row[2].strip() if len(row) > 2 and row[2].strip() else ""
        sector = row[3].strip() if len(row) > 3 and row[3].strip() else ""
        pct = parse_num(row[4]) if len(row) > 4 else None
        lev_pct = parse_num(row[5]) if len(row) > 5 else None
        eq_pct = parse_num(row[6]) if len(row) > 6 else None
        
        if not ticker or not pct or pct < 0.01:
            continue
        
        s = {"ticker": ticker, "sector": sector, "pct": round(pct, 2)}
        if lev_pct is not None:
            s["leverage_pct"] = lev_pct
        if eq_pct is not None:
            s["equity_pct"] = eq_pct
        stocks.append(s)
        sectors_sum[sector] = sectors_sum.get(sector, 0) + pct
    
    total_stock_pct = sum(s["pct"] for s in stocks)
    cash_pct = round(100.0 - total_stock_pct, 2)
    if cash_pct < 0:
        cash_pct = 0.0
    
    # Sectors
    sectors = []
    for sector, pct in sorted(sectors_sum.items(), key=lambda x: -x[1]):
        sector_stocks = [s["ticker"] for s in stocks if s["sector"] == sector]
        sectors.append({"sector": sector, "pct": round(pct, 2), "stocks": sector_stocks})
    if cash_pct > 0:
        sectors.append({"sector": "Cash", "pct": cash_pct, "stocks": ["Cash"]})
    
    # Latest KPIs
    latest = portfolio[-1]
    first_this_year = None
    this_year = latest["date"][:4]
    for e in portfolio:
        if e["date"].startswith(this_year):
            first_this_year = e
            break
    
    ytd_ret = round(latest.get("ret_inception", 0) - first_this_year.get("ret_inception", 0), 1) if first_this_year else None
    
    output = {
        "generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latest": {
            "date": latest.get("date"),
            "nab": latest.get("nab"),
            "ihsg": latest.get("ihsg"),
            "ret_inception": latest.get("ret_inception"),
            "ihsg_inception": latest.get("ihsg_inception"),
            "cagr": latest.get("cagr"),
            "leverage": latest.get("leverage"),
            "asset_value": latest.get("asset_value"),
            "ytd_ret": ytd_ret,
            "cash_pct": cash_pct,
            "total_stock_pct": round(total_stock_pct, 2),
            "stocks_count": len(stocks)
        },
        "stocks": stocks,
        "sectors": sectors,
        "historical": portfolio
    }
    
    out_path = os.path.join(OUT_DIR, "dashboard-data.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    
    print(f"\n✅ Exported to: {out_path}")
    print(f"   {len(stocks)} stocks across {len(sectors)} sectors")
    print(f"   Cash: {cash_pct}%")
    print(f"   Latest ({latest['date']}): Ret={latest.get('ret_inception')}% | CAGR={latest.get('cagr')}% | YTD={ytd_ret}% | Lev={latest.get('leverage')}%")

if __name__ == "__main__":
    main()
