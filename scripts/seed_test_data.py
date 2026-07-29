"""Seed the database with realistic test listings from all 3 sources."""
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DB = Path("data") / "leads.db"

RECORDS = [
    # ---- Justdial listings ----
    {"company_name": "TechSol IT Services", "website": "https://techsol.in", "email": "info@techsol.in", "phone": "9876543210", "address": "Sector 62, Noida, Uttar Pradesh", "industry_code": "IT Services", "source_url": "https://www.justdial.com/Delhi/IT-Services/nct-10278073"},
    {"company_name": "Webify Solutions", "website": "https://webify.in", "email": "contact@webify.in", "phone": "9812345678", "address": "Connaught Place, Delhi", "industry_code": "Software Development", "source_url": "https://www.justdial.com/Delhi/IT-Services/nct-10278073"},
    {"company_name": "CloudBase Technologies", "website": "https://cloudbase.in", "email": "sales@cloudbase.in", "phone": "9911223344", "address": "HITEC City, Hyderabad, Telangana", "industry_code": "Cloud Computing", "source_url": "https://www.justdial.com/Delhi/IT-Services/nct-10278073"},
    {"company_name": "DataPulse Analytics", "website": "", "email": "hello@datapulse.in", "phone": "9876501234", "address": "MG Road, Bengaluru, Karnataka", "industry_code": "Data Analytics", "source_url": "https://www.justdial.com/Delhi/IT-Services/nct-10278073"},
    {"company_name": "NetPro Security", "website": "https://netpro.in", "email": "", "phone": "8765432109", "address": "Andheri East, Mumbai, Maharashtra", "industry_code": "Cybersecurity", "source_url": "https://www.justdial.com/Delhi/IT-Services/nct-10278073"},

    # ---- IndiaMART listings ----
    {"company_name": "Synergy Software Pvt Ltd", "website": "https://synergysoft.in", "email": "info@synergysoft.in", "phone": "9312345678", "address": "Lajpat Nagar, New Delhi", "industry_code": "Software Development Services", "source_url": "https://dir.indiamart.com/new-delhi/software-development-services.html"},
    {"company_name": "Alpha Digital Solutions", "website": "https://alphadigital.in", "email": "contact@alphadigital.in", "phone": "9899123456", "address": "Banjara Hills, Hyderabad, Telangana", "industry_code": "Digital Marketing", "source_url": "https://dir.indiamart.com/new-delhi/software-development-services.html"},
    {"company_name": "GreenCode Labs", "website": "https://greencode.in", "email": "team@greencode.in", "phone": "9810098100", "address": "Koramangala, Bengaluru, Karnataka", "industry_code": "Custom Software", "source_url": "https://dir.indiamart.com/new-delhi/software-development-services.html"},
    {"company_name": "Orbit Infotech", "website": "", "email": "info@orbitinfotech.in", "phone": "9811111111", "address": "Shivaji Nagar, Pune, Maharashtra", "industry_code": "Web Development", "source_url": "https://dir.indiamart.com/new-delhi/software-development-services.html"},
    {"company_name": "SafeNet Solutions", "website": "https://safenet.in", "email": "", "phone": "9898989898", "address": "Sahibabad, Ghaziabad, Uttar Pradesh", "industry_code": "Network Security", "source_url": "https://dir.indiamart.com/new-delhi/software-development-services.html"},

    # ---- TradeIndia listings ----
    {"company_name": "Zeta Consultants", "website": "https://zetaconsult.in", "email": "info@zetaconsult.in", "phone": "9876540987", "address": "Viman Nagar, Pune, Maharashtra", "industry_code": "IT Consultancy", "source_url": "https://www.tradeindia.com/manufacturers/it-consultancy.html"},
    {"company_name": "NexGen IT Solutions", "website": "https://nexgenit.in", "email": "sales@nexgenit.in", "phone": "9812340000", "address": "Electronic City, Bengaluru, Karnataka", "industry_code": "IT Consulting", "source_url": "https://www.tradeindia.com/manufacturers/it-consultancy.html"},
    {"company_name": "DigitalForge Technologies", "website": "", "email": "info@digitalforge.in", "phone": "9999888777", "address": "Gachibowli, Hyderabad, Telangana", "industry_code": "Software Consulting", "source_url": "https://www.tradeindia.com/manufacturers/it-consultancy.html"},
    {"company_name": "PrimeStack Solutions", "website": "https://primestack.in", "email": "", "phone": "9876512345", "address": "Whitefield, Bengaluru, Karnataka", "industry_code": "IT Services", "source_url": "https://www.tradeindia.com/manufacturers/it-consultancy.html"},
    {"company_name": "Apex IT Consulting", "website": "https://apexitc.in", "email": "contact@apexitc.in", "phone": "9000011111", "address": "Ashram, New Delhi", "industry_code": "IT Consultancy", "source_url": "https://www.tradeindia.com/manufacturers/it-consultancy.html"},

    # ---- Duplicate record (same dedup_key as TechSol) ----
    {"company_name": "TechSol IT Services Ltd", "website": "https://techsol.in", "email": "", "phone": "", "address": "Sector 62, Noida, UP", "industry_code": "IT Services", "source_url": "https://www.justdial.com/Delhi/IT-Services/nct-10278073"},
]


def seed():
    DB.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(DB))
    cur = conn.cursor()

    now = datetime.now(timezone.utc).isoformat()
    headers = ["company_name", "website", "email", "phone", "address", "industry_code", "employee_count", "revenue_band", "source_url", "scraped_at", "dedup_key", "lead_score"]
    placeholders = ",".join("?" for _ in headers)

    for table in ("Leads", "staging", "scrape_errors", "rejected_duplicates"):
        cur.execute(f"DELETE FROM \"{table}\"")

    rows = []
    for r in RECORDS:
        web = r.get("website") or ""
        dedup_key = ""
        if web:
            try:
                parsed = urlparse(web)
                host = parsed.netloc.lower() or web.lower()
                dedup_key = host.removeprefix("www.").split("/")[0]
            except Exception:
                dedup_key = web.lower()

        score = 0
        if r.get("email"):
            score += 25
        if r.get("phone"):
            score += 25
        if r.get("website"):
            score += 20
        if r.get("industry_code"):
            score += 10
        score = min(score, 100)

        rows.append((
            r["company_name"],
            r.get("website", "") or "",
            r.get("email", "") or "",
            r.get("phone", "") or "",
            r.get("address", "") or "",
            r.get("industry_code", "") or None,
            None,
            None,
            r["source_url"],
            now,
            dedup_key,
            str(score),
        ))

    cur.executemany(f"INSERT INTO Leads ({','.join(headers)}) VALUES ({placeholders})", rows)
    cur.executemany(f"INSERT INTO staging ({','.join(headers)}) VALUES ({placeholders})", rows)
    conn.commit()
    conn.close()

    jd = sum(1 for r in RECORDS if "justdial" in r["source_url"])
    im = sum(1 for r in RECORDS if "indiamart" in r["source_url"])
    ti = sum(1 for r in RECORDS if "tradeindia" in r["source_url"])
    print(f"Seeded {len(rows)} records into Leads and staging tabs")
    print(f"  Sources: {jd} Justdial, {im} IndiaMART, {ti} TradeIndia, {len(rows) - jd - im - ti} duplicate")


if __name__ == "__main__":
    seed()
