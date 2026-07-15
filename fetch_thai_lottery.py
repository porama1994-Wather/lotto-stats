# -*- coding: utf-8 -*-
"""
fetch_thai_lottery.py
ดึงผลหวยรัฐบาลไทยย้อนหลัง จาก lotto.thaiorc.com (หน้าสถิติรายปี) -> results_thai.json

วิธีใช้:
    pip install requests beautifulsoup4
    python fetch_thai_lottery.py                            # ดึง 10 ปี (2560-2569)
    python fetch_thai_lottery.py --merge results_thai.json  # รันซ้ำ อัปเดตงวดใหม่

รูปแบบ JSON:
[
  {"date": "2026-07-01", "first6": "751495", "last2": "62",
   "front3": ["001","980"], "last3": ["304","531"]},
  ...
]

ข้อดีของหวยไทย: ออกแค่ ~24-25 งวด/ปี หน้ารายปีของเว็บต้นทางจึงแสดงครบทั้งปี
-> รันครั้งแรกได้ข้อมูล 10 ปีเต็มเลย (ต่างจากหวยลาวที่ถูกตัดเหลืองวดล่าสุด)
"""

import argparse
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

YEARS_BE = list(range(2560, 2570))   # พ.ศ.2560 (ค.ศ.2017) ถึง 2569 (ค.ศ.2026)
URL_TMPL = "https://lotto.thaiorc.com/thai/stats/lottery-year{year}.php"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ThaiLottoStats/1.0; personal statistics project)"
}
DELAY_SEC = 1.5
TIMEOUT = 20

# วันที่(พ.ศ.) รางวัลที่1(6ตัว) เลขท้าย2ตัว เลขหน้า3ตัว x2 เลขท้าย3ตัว x2
ROW_RE = re.compile(
    r"(\d{2}/\d{2}/25\d{2})\s+(\d{6})\s+(\d{2})\s+(\d{3})\s+(\d{3})\s+(\d{3})\s+(\d{3})\b")


def be_date_to_iso(d: str):
    try:
        day, month, year_be = d.split("/")
        return date(int(year_be) - 543, int(month), int(day)).isoformat()
    except Exception:
        return None


def parse_page(html: str):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    out = []
    for m in ROW_RE.finditer(text):
        iso = be_date_to_iso(m.group(1))
        if not iso:
            continue
        out.append({
            "date": iso,
            "first6": m.group(2),
            "last2": m.group(3),
            "front3": [m.group(4), m.group(5)],
            "last3": [m.group(6), m.group(7)],
        })
    return out


def fetch(url: str):
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = "windows-874"
        return r.text
    except requests.RequestException as e:
        print(f"  [ข้าม] ดึงไม่สำเร็จ: {url} ({e})", file=sys.stderr)
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merge", help="ไฟล์ results_thai.json เดิมที่จะรวมข้อมูล")
    ap.add_argument("--out", default="results_thai.json")
    args = ap.parse_args()

    all_records = {}
    if args.merge and Path(args.merge).exists():
        for rec in json.loads(Path(args.merge).read_text(encoding="utf-8")):
            all_records[rec["date"]] = rec
        print(f"โหลดข้อมูลเดิม {len(all_records)} งวด จาก {args.merge}")

    for year in YEARS_BE:
        url = URL_TMPL.format(year=year)
        print(f"กำลังดึง ปี พ.ศ.{year}: {url}")
        html = fetch(url)
        if not html:
            continue
        recs = parse_page(html)
        new = sum(1 for r in recs if r["date"] not in all_records)
        for r in recs:
            all_records.setdefault(r["date"], r)
        print(f"  พบ {len(recs)} งวด (ใหม่ {new})")
        time.sleep(DELAY_SEC)

    out = sorted(all_records.values(), key=lambda r: r["date"])
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nบันทึก {len(out)} งวด -> {args.out}")
    if out:
        print(f"ช่วงข้อมูล: {out[0]['date']} ถึง {out[-1]['date']}")
        print("ตัวอย่าง 2 งวดล่าสุด:")
        for r in out[-2:]:
            print(" ", r)
    print("\n*** อย่าลืมสุ่มตรวจผลลัพธ์เทียบกับเว็บจริงก่อนใช้ ***")


if __name__ == "__main__":
    main()
