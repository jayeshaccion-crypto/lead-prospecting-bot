"""Generate a standalone HTML dashboard from the lead database."""
import sqlite3, json, re
from pathlib import Path
from datetime import datetime
from collections import Counter

DB = Path("data") / "leads.db"
OUT = Path("dashboard.html")

SOURCE_MAP = {
    "justdial.com": "Justdial",
    "indiamart.com": "IndiaMART",
    "tradeindia.com": "TradeIndia",
}


def _source_name(url: str | None) -> str:
    if not url:
        return "Unknown"
    for domain, label in SOURCE_MAP.items():
        if domain in url:
            return label
    return url.split("/")[2] if "//" in url else "Unknown"


def build():
    if not DB.exists():
        print(f"Database not found at {DB} — nothing to build")
        return 0

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT company_name, website, email, phone, address, industry_code, dedup_key, source_url FROM Leads ORDER BY company_name")
    rows = []
    for r in cur.fetchall():
        d = dict(r)
        d["source"] = _source_name(d.get("source_url"))
        rows.append(d)

    total = len(rows)
    phones = sum(1 for r in rows if r.get("phone"))
    emails = sum(1 for r in rows if r.get("email"))
    websites = sum(1 for r in rows if r.get("website"))
    domains = sum(1 for r in rows if r.get("dedup_key"))
    source_counts = Counter(r["source"] for r in rows)

    conn.close()
    data_json = json.dumps(rows)

    source_options = "".join(
        f'<option value="{s}">{s} ({c})</option>'
        for s, c in sorted(source_counts.items())
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Lead Prospecting Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400;14..32,500;14..32,600;14..32,700&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  font-family:'Inter',-apple-system,sans-serif;
  background:#f0f4f8; color:#1a2332;
  padding:32px 24px; line-height:1.5;
}}
.header {{
  max-width:1280px; margin:0 auto 32px;
  display:flex; justify-content:space-between; align-items:flex-end; flex-wrap:wrap; gap:16px;
}}
.header h1 {{
  font-size:28px; font-weight:700;
  background:linear-gradient(135deg,#1a2332,#3b82f6);
  -webkit-background-clip:text; -webkit-text-fill-color:transparent;
}}
.header .sub {{ color:#64748b; font-size:14px; margin-top:4px; }}
.header .badge {{
  background:#fff; border-radius:100px; padding:8px 20px;
  font-size:13px; font-weight:600; color:#1a2332;
  box-shadow:0 1px 3px rgba(0,0,0,.08);
  display:inline-flex; align-items:center; gap:8px;
}}
.header .badge span {{ color:#3b82f6; font-size:18px; }}
.cards {{
  max-width:1280px; margin:0 auto;
  display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
  gap:16px; margin-bottom:28px;
}}
.card {{
  background:#fff; border-radius:14px; padding:20px 24px;
  box-shadow:0 1px 3px rgba(0,0,0,.06);
  transition:transform .15s,box-shadow .15s;
}}
.card:hover {{ transform:translateY(-2px); box-shadow:0 8px 25px rgba(0,0,0,.08); }}
.card .lbl {{ font-size:11px; font-weight:600; color:#94a3b8; text-transform:uppercase; letter-spacing:.5px; }}
.card .val {{ font-size:28px; font-weight:700; margin-top:6px; }}
.val.blue {{ color:#3b82f6; }} .val.gold {{ color:#f59e0b; }}
.val.green {{ color:#10b981; }} .val.purple {{ color:#8b5cf6; }}
.val.red {{ color:#ef4444; }} .val.teal {{ color:#06b6d4; }}
.controls {{
  max-width:1280px; margin:0 auto 16px;
  display:flex; gap:10px; flex-wrap:wrap; align-items:center;
}}
.controls input,.controls select {{
  padding:10px 14px; border:1px solid #e2e8f0; border-radius:8px;
  font-size:13px; font-family:inherit; background:#fff;
  outline:none; transition:border-color .15s; color:#1a2332;
}}
.controls input:focus,.controls select:focus {{ border-color:#3b82f6; }}
.controls input {{ flex:1 1 220px; }}
.controls select {{ width:auto; min-width:130px; }}
.controls .cnt {{ font-size:13px; color:#64748b; margin-left:auto; white-space:nowrap; }}
.wrap {{
  max-width:1280px; margin:0 auto;
  background:#fff; border-radius:14px; box-shadow:0 1px 3px rgba(0,0,0,.06);
  overflow-x:auto;
}}
table {{ width:100%; border-collapse:collapse; font-size:13px; min-width:1000px; }}
thead {{ background:#f8fafc; }}
th {{
  text-align:left; padding:14px 14px; font-weight:600; font-size:11px;
  color:#64748b; text-transform:uppercase; letter-spacing:.5px;
  border-bottom:1px solid #e2e8f0; white-space:nowrap; cursor:pointer;
  user-select:none; position:sticky; top:0; background:#f8fafc;
}}
th:hover {{ color:#3b82f6; }}
td {{ padding:12px 14px; border-bottom:1px solid #f1f5f9; }}
tr:hover td {{ background:#f8fafc; }}
.empt {{ color:#94a3b8; font-style:italic; }}
.tel {{ font-variant-numeric:tabular-nums; }}
.adr {{ color:#475569; max-width:200px; }}
.ind {{ color:#64748b; max-width:160px; }}
.src-badge {{
  display:inline-block; padding:2px 8px; border-radius:4px;
  font-size:11px; font-weight:600; white-space:nowrap;
}}
.src-justdial {{ background:#e0f2fe; color:#0369a1; }}
.src-indiamart {{ background:#fef3c7; color:#92400e; }}
.src-tradeindia {{ background:#d1fae5; color:#065f46; }}
.src-unknown {{ background:#f1f5f9; color:#64748b; }}
.foot {{ max-width:1280px; margin:20px auto 0; text-align:center; font-size:12px; color:#94a3b8; }}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>Lead Prospecting Dashboard</h1>
    <div class="sub">Live aggregated data from Indian business directories</div>
  </div>
  <div class="badge"><span>&#9679;</span> {datetime.now().strftime("%b %d, %Y at %I:%M %p")}</div>
</div>

<div class="cards">
  <div class="card"><div class="lbl">Total Leads</div><div class="val blue">{total}</div></div>
  <div class="card"><div class="lbl">With Phone</div><div class="val green">{phones}</div></div>
  <div class="card"><div class="lbl">With Email</div><div class="val purple">{emails}</div></div>
  <div class="card"><div class="lbl">With Website</div><div class="val red">{websites}</div></div>
  <div class="card"><div class="lbl">Unique Domains</div><div class="val teal">{domains}</div></div>
</div>

<div class="controls">
  <input type="text" id="q" placeholder="Search name, phone, address, industry..." oninput="draw()">
  <select id="srcf" onchange="draw()">
    <option value="">All sources</option>
    {source_options}
  </select>
  <select id="hasf" onchange="draw()">
    <option value="">Any fields</option>
    <option value="phone">Has phone</option>
    <option value="email">Has email</option>
    <option value="website">Has website</option>
    <option value="phone_email">Has phone &amp; email</option>
  </select>
  <div class="cnt" id="cnt"></div>
</div>

<div class="wrap">
<table>
<thead><tr>
  <th onclick="sort(0)">#</th>
  <th onclick="sort(1)">Company</th>
  <th onclick="sort(2)">Source</th>
  <th onclick="sort(3)">Phone</th>
  <th onclick="sort(4)">Email</th>
  <th onclick="sort(5)">Website</th>
  <th onclick="sort(6)">Address</th>
  <th onclick="sort(7)">Industry</th>
</tr></thead>
<tbody id="tb"></tbody>
</table>
</div>

<div class="foot">Lead Prospecting Pipeline &mdash; Built with Scrapling &amp; SQLite</div>

<script>
const _data = {data_json};
function _c(v) {{ return (v===null||v===undefined||String(v).trim()==='')?'<span class="empt">\u2014</span>':String(v); }}
function _s(src) {{
  var cls='src-unknown';
  if(src==='Justdial') cls='src-justdial';
  else if(src==='IndiaMART') cls='src-indiamart';
  else if(src==='TradeIndia') cls='src-tradeindia';
  return '<span class="src-badge '+cls+'">'+src+'</span>';
}}
const _f = ['company_name','source','phone','email','website','address','industry_code'];
let _sc=-1,_sa=true;

function draw() {{
  var q=document.getElementById('q').value.toLowerCase();
  var srcf=document.getElementById('srcf').value;
  var hasf=document.getElementById('hasf').value;
  var rows=_data.filter(function(r){{
    var s=(r.company_name+' '+(r.phone||'')+' '+(r.address||'')+' '+(r.industry_code||'')).toLowerCase();
    if(q&&!s.includes(q)) return false;
    if(srcf&&r.source!==srcf) return false;
    if(hasf==='phone'&&!r.phone) return false;
    if(hasf==='email'&&!r.email) return false;
    if(hasf==='website'&&!r.website) return false;
    if(hasf==='phone_email'&&(!r.phone||!r.email)) return false;
    return true;
  }});
  if(_sc>=0){{var k=_f[_sc];rows.sort(function(a,b){{
    var va=(a[k]===null||a[k]===undefined?'':String(a[k])).toLowerCase();
    var vb=(b[k]===null||b[k]===undefined?'':String(b[k])).toLowerCase();
    return va<vb?_sa?-1:1:va>vb?_sa?1:-1:0;
  }});}}
  document.getElementById('cnt').textContent='Showing '+rows.length+' of '+_data.length;
  document.getElementById('tb').innerHTML=rows.map(function(r,i){{
    return '<tr><td>'+(i+1)+'</td><td><strong>'+_c(r.company_name)+'</strong></td>'+
      '<td>'+_s(r.source)+'</td>'+
      '<td class="tel">'+_c(r.phone)+'</td><td>'+_c(r.email)+'</td>'+
      '<td>'+_c(r.website)+'</td><td class="adr">'+_c(r.address)+'</td>'+
      '<td class="ind">'+_c(r.industry_code).substring(0,120)+'</td></tr>';
  }}).join('');
}}

function sort(c){{if(_sc===c)_sa=!_sa;else{{_sc=c;_sa=true;}}draw();}}
draw();
</script>
</body>
</html>"""

    OUT.write_text(html, encoding="utf-8")
    print(f"Dashboard written to {OUT.resolve()} ({len(rows)} records)")
    return len(rows)


if __name__ == "__main__":
    build()
