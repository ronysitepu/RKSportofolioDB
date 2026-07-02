#!/usr/bin/env python3
"""
Generate dashboard-data.json for RKSportofolioDB.
Reads Historical Data and Stock Proportion from Google Sheet via Composio API.
"""

import json, os, re, sys, datetime, urllib.request, urllib.error

SHEET_ID = "1nuM9lZ6fHTHw09KcWIWhXK6uyELS1xtM1QlG-YcLILs"
HOME = os.path.expanduser("~")
BASE_URL = "https://backend.composio.dev/api/v1"
OUT_DIR = os.path.expanduser("~/RKSportofolioDB")

def load_config():
    config_path = os.path.join(HOME, ".hermes", "config.yaml")
    api_key = None
    with open(config_path) as f:
        for line in f:
            if "x-api-key:" in line:
                api_key = line.split(":", 1)[1].strip()
    acct_id = "ca_PK_775oMWhHz"
    return api_key, acct_id

def run_action(action, body):
    api_key, acct_id = load_config()
    url = BASE_URL + "/actions/execute"
    payload = {"actionName": action, "connectedAccountId": acct_id, "requestBody": body}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
        headers={"x-api-key": api_key, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())

def batch_get(ranges):
    return run_action("GOOGLESHEETS_BATCH_GET", {"spreadsheet_id": SHEET_ID, "ranges": ranges})

def parse_num(v):
    if v is None or v == "": return None
    v = v.strip().replace(",", "").replace(" ", "")
    if v == "": return None
    try: return float(v.replace("%", ""))
    except: return None

def parse_date(d):
    import re
    m = re.match(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', d.strip() if d else "")
    if m:
        day, month, year = m.groups()
        year = int(year)
        if year < 100: year += 2000
        return f"{year:04d}-{int(month):02d}-{int(day):02d}"
    return d.strip() if d else None

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("Reading Google Sheet...")
    result = batch_get(["'Historical Data'!A1:O750", "'Stock Proportion'!A1:G30"])
    data = result.get("data", result)
    if "data" in data: data = data["data"]
    vr = data.get("valueRanges", [])
    if not vr:
        print("Error: no data", list(data.keys())[:5])
        return
    hist_raw, prop_raw = vr[0]["values"], vr[1]["values"]
    
    portfolio = []
    for row in hist_raw[1:]:
        if len(row) < 8: continue
        date_str = parse_date(row[0] if len(row) > 0 else None)
        if not date_str: continue
        nab = parse_num(row[4]) if len(row) > 4 else None
        ihsg = parse_num(row[5]) if len(row) > 5 else None
        if nab is None and ihsg is None: continue
        entry = {"date": date_str}
        if nab is not None: entry["nab"] = nab
        if ihsg is not None: entry["ihsg"] = ihsg
        for col, key in [(8,"ret_inception"),(9,"ihsg_inception"),(13,"cagr"),(14,"leverage"),(2,"asset_value"),(6,"ret_weekly"),(7,"ihsg_ret_weekly")]:
            v = parse_num(row[col]) if len(row) > col else None
            if v is not None: entry[key] = v
        portfolio.append(entry)
    
    stocks, sectors_sum = [], {}
    for row in prop_raw[1:]:
        if len(row) < 5: continue
        ticker = row[2].strip() if len(row) > 2 and row[2].strip() else ""
        sector = row[3].strip() if len(row) > 3 and row[3].strip() else ""
        pct = parse_num(row[4])
        if not ticker or not pct or pct < 0.01: continue
        stocks.append({"ticker": ticker, "sector": sector, "pct": round(pct, 2)})
        sectors_sum[sector] = sectors_sum.get(sector, 0) + pct
    
    total_stock_pct = sum(s["pct"] for s in stocks)
    cash_pct = round(max(0, 100.0 - total_stock_pct), 2)
    cash_pct = max(cash_pct, 0.0)
    
    sectors = []
    for sector, pct in sorted(sectors_sum.items(), key=lambda x: -x[1]):
        sector_stocks = [s["ticker"] for s in stocks if s["sector"] == sector]
        sectors.append({"sector": sector, "pct": round(pct, 2), "stocks": sector_stocks})
    if cash_pct > 0:
        sectors.append({"sector": "Cash", "pct": cash_pct, "stocks": ["Cash"]})
    
    latest = portfolio[-1]
    first_this_year = None
    for e in portfolio:
        if e["date"].startswith(latest["date"][:4]):
            first_this_year = e
            break
    ytd_ret = round(latest.get("ret_inception", 0) - first_this_year.get("ret_inception", 0), 1) if first_this_year else None
    
    output = {"generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latest": {"date": latest.get("date"),"nab": latest.get("nab"),"ihsg": latest.get("ihsg"),
            "ret_inception": latest.get("ret_inception"),"ihsg_inception": latest.get("ihsg_inception"),
            "cagr": latest.get("cagr"),"leverage": latest.get("leverage"),"asset_value": latest.get("asset_value"),
            "ytd_ret": ytd_ret,"cash_pct": cash_pct,"total_stock_pct": round(total_stock_pct, 2),
            "stocks_count": len(stocks)},
        "stocks": stocks,"sectors": sectors,"historical": portfolio}
    
    out_path = os.path.join(OUT_DIR, "dashboard-data.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Done: {len(portfolio)} data points, {len(stocks)} stocks")

if __name__ == "__main__":
    main()
