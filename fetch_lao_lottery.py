# -*- coding: utf-8 -*-
"""
fetch_lao_lottery.py
ดึงผลหวยลาวพัฒนา จาก lotto.thaiorc.com (หน้าสถิติแยกรายปี) -> เก็บเป็น results.json

วิธีใช้:
    pip install requests beautifulsoup4
    python fetch_lao_lottery.py                       # ดึงทุกปีที่ตั้งไว้ บันทึกเป็น results.json
    python fetch_lao_lottery.py --merge results.json  # รันซ้ำ อัปเดตงวดใหม่ต่อของเดิม (ใช้ตอน Actions)

รูปแบบ JSON ที่ได้ (ตรงกับที่หน้าเว็บใช้):
[
  {"date": "2025-12-31", "n4": "4541", "top3": "541", "top2": "41", "low2": "45"},
  ...
]

*** ข้อจำกัดสำคัญที่ต้องรู้ ***
เว็บต้นทางนี้ "ไม่รองรับการเปลี่ยนหน้า" จริงๆ (พารามิเตอร์ ?pg=2 ก็ส่งเนื้อหาหน้าแรกซ้ำ)
แต่ละหน้ารายปีโชว์ได้แค่ ~26-30 งวดล่าสุดของปีนั้นเท่านั้น (ไม่ใช่ทั้งปี)
เพราะฉะนั้นการรันครั้งแรกจะได้ข้อมูลแค่ไม่กี่เดือนล่าสุดของแต่ละปีที่ตั้งไว้ ไม่ใช่ 10 ปีเต็มทันที
วิธีให้ข้อมูลสะสมครบ 10 ปีจริง: ปล่อยให้ GitHub Actions รันตามตารางเวลาไปเรื่อยๆ
(สคริปต์ใช้ --merge สะสมงวดใหม่ต่อของเดิมทุกครั้ง) ข้อมูลจะเพิ่มขึ้นเองตามเวลาจริงที่ผ่านไป
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

# ปีพ.ศ. ที่จะไล่ดึง (2560 = ค.ศ.2017 ... 2569 = ค.ศ.2026) ครอบคลุม 10 ปี
YEARS_BE = list(range(2560, 2570))
URL_TMPL = "https://lotto.thaiorc.com/lao/stats/lottery-year{year}.php"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LaoLottoStats/1.0; personal statistics project)"
}
DELAY_SEC = 1.5
TIMEOUT = 20

# วันที่ (พ.ศ.) ตามด้วยเลข 6 ตัว, 3 ตัวบน, 2 ตัวบน, 2 ตัวล่าง
ROW_RE = re.compile(r"(\d{2}/\d{2}/25\d{2})\s+(\d{6})\s+(\d{3})\s+(\d{2})\s+(\d{2})\b")


def be_date_to_iso(d: str):
    try:
        day, month, year_be = d.split("/")
        year = int(year_be) - 543
        return date(year, int(month), int(day)).isoformat()
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
        n6 = m.group(2)
        out.append({
            "date": iso,
            "n4": n6[-4:],          # ใช้ 4 ตัวท้ายของเลข 6 ตัว ให้ตรงกับ schema เดิม
            "top3": m.group(3),
            "top2": m.group(4),
            "low2": m.group(5),     # ตอนนี้มีค่าจริงแล้ว ไม่ใช่ null
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
    ap.add_argument("--merge", help="ไฟล์ results.json เดิมที่จะรวมข้อมูลเข้าด้วยกัน")
    ap.add_argument("--out", default="results.json")
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
            # อัปเดตทับถ้าของเดิมไม่มี low2 แต่ของใหม่มี (เผื่อรันซ้ำจาก source เก่า)
            old = all_records.get(r["date"])
            if old is None or (old.get("low2") is None and r.get("low2")):
                all_records[r["date"]] = r
        print(f"  พบ {len(recs)} งวด (ใหม่ {new})")
        time.sleep(DELAY_SEC)

    out = sorted(all_records.values(), key=lambda r: r["date"])
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nบันทึก {len(out)} งวด -> {args.out}")
    if out:
        print(f"ช่วงข้อมูล: {out[0]['date']} ถึง {out[-1]['date']}")
        print("ตัวอย่าง 3 งวดล่าสุด:")
        for r in out[-3:]:
            print(" ", r)
    print("\n*** อย่าลืมสุ่มตรวจผลลัพธ์เทียบกับเว็บจริงก่อนใช้ ***")
    print("*** หมายเหตุ: เว็บนี้โชว์แค่งวดล่าสุดต่อปี ข้อมูลจะสะสมครบมากขึ้นเมื่อรันซ้ำไปเรื่อยๆ (ดูคำอธิบายบนสุดของไฟล์นี้) ***")


if __name__ == "__main__":
    main()
