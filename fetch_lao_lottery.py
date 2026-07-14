# -*- coding: utf-8 -*-
"""
fetch_lao_lottery.py
ดึงผลหวยลาวพัฒนาย้อนหลัง -> เก็บเป็น results.json สำหรับหน้าเว็บสถิติ

วิธีใช้:
    pip install requests beautifulsoup4
    python fetch_lao_lottery.py                 # ดึงตาม URL ใน SOURCES
    python fetch_lao_lottery.py --merge old.json  # รวมกับไฟล์เดิม (กันข้อมูลหาย)

รูปแบบ JSON ที่ได้ (ตรงกับที่หน้าเว็บใช้):
[
  {"date": "2026-07-13", "n4": "3026", "top3": "026", "top2": "26", "low2": "77"},
  ...
]

หมายเหตุสำคัญ:
- เว็บผลหวยแต่ละเจ้า HTML ไม่เหมือนกันและเปลี่ยนได้ ให้รันแล้วตรวจผลลัพธ์
  งวดแรกๆ เทียบกับหน้าเว็บจริงก่อนใช้จริงเสมอ
- สคริปต์นี้ใช้วิธี "จับ pattern ข้อความ" (regex) แทนการ lock ที่ HTML class
  เพื่อให้ทนต่อการเปลี่ยน layout มากขึ้น
- โปรดเคารพเว็บต้นทาง: มี delay ระหว่าง request, อย่ารันถี่, และตรวจ
  เงื่อนไขการใช้งาน (ToS) ของเว็บนั้นๆ ก่อนนำข้อมูลไปเผยแพร่ต่อ
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

# ---------------------------------------------------------------------------
# 1) แหล่งข้อมูล — ใส่ URL หน้า "ผลย้อนหลังรายปี/รายเดือน" ที่ต้องการดึง
#    ตัวอย่างแหล่งที่มีข้อมูลย้อนหลังยาว (เลือกใช้ + เติม URL รายปีเอง):
#    - https://horoscope.thaiorc.com/lotto/lao/stats/lottery-years10.php  (รวม 10 ปี)
#    - https://www.raakaadee.com/ตรวจหวย-หุ้น/หวยลาวพัฒนา/   (รายวัน/ย้อนหลัง)
#    - https://www.sanook.com/news/archive/laolotto/          (archive รายงวด)
#    - https://www.tnews.co.th/... (หน้าสถิติรายปี 2566-2569)
# ---------------------------------------------------------------------------
SOURCES = [
    # thaiorc: สถิติหวยลาวย้อนหลัง 10 ปี (822 งวด แบ่ง 4 หน้า) — ทดสอบแล้วดึงได้จริง
    "https://horoscope.thaiorc.com/lotto/lao/stats/lottery-years10.php",
    "https://horoscope.thaiorc.com/lotto/lao/stats/lottery-years10.php?pg=2",
    "https://horoscope.thaiorc.com/lotto/lao/stats/lottery-years10.php?pg=3",
    "https://horoscope.thaiorc.com/lotto/lao/stats/lottery-years10.php?pg=4",
    # เติม URL เว็บอื่นเพิ่มได้ (เช่นหน้ารายปีของ tnews/sanook)
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LaoLottoStats/1.0; personal statistics project)"
}
DELAY_SEC = 2.0          # หน่วงระหว่าง request กันโดนบล็อก/กันรบกวนเว็บต้นทาง
TIMEOUT = 20

# เดือนไทย -> เลขเดือน
TH_MONTHS = {
    "ม.ค.": 1, "มกราคม": 1, "ก.พ.": 2, "กุมภาพันธ์": 2, "มี.ค.": 3, "มีนาคม": 3,
    "เม.ย.": 4, "เมษายน": 4, "พ.ค.": 5, "พฤษภาคม": 5, "มิ.ย.": 6, "มิถุนายน": 6,
    "ก.ค.": 7, "กรกฎาคม": 7, "ส.ค.": 8, "สิงหาคม": 8, "ก.ย.": 9, "กันยายน": 9,
    "ต.ค.": 10, "ตุลาคม": 10, "พ.ย.": 11, "พฤศจิกายน": 11, "ธ.ค.": 12, "ธันวาคม": 12,
}

# pattern วันที่ไทย เช่น "13 ก.ค. 2569" หรือ "13 กรกฎาคม 2569"
DATE_RE = re.compile(r"(\d{1,2})\s*(" + "|".join(map(re.escape, TH_MONTHS)) + r")\s*(\d{4})")
# pattern วันที่ตัวเลข เช่น 13/7/69, 13/07/2569
DATE_NUM_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{2,4})")
# pattern ผลรางวัล เช่น "เลข 4 ตัว : 3026" / "4 ตัว 3026"
N4_RE = re.compile(r"4\s*ต[ัวั]?ว\D{0,8}(\d{4})")
LOW2_RE = re.compile(r"2\s*ต[ัวั]?ว\s*ล่?าง\D{0,8}(\d{2})")


def to_iso(day: int, month: int, year: int) -> str | None:
    """แปลง พ.ศ./ค.ศ. เป็น ISO date, คืน None ถ้าไม่สมเหตุสมผล"""
    if year > 2400:          # พ.ศ.
        year -= 543
    elif year < 100:         # ปีย่อ เช่น 69 -> 2569 -> 2026
        year = year + 2500 - 543
    try:
        d = date(year, month, day)
    except ValueError:
        return None
    if not (2010 <= d.year <= date.today().year):
        return None
    return d.isoformat()


def parse_page(html: str) -> list[dict]:
    """
    แปลงหน้า HTML เป็นรายการผลหวย
    กลยุทธ์: กวาดข้อความทั้งหน้า แล้วจับคู่ 'วันที่' ที่อยู่ใกล้ 'เลข 4 ตัว'
    ถ้าเว็บที่ใช้โครงสร้างต่างมาก ให้เขียน parser เฉพาะเพิ่มด้านล่าง
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    results = []

    # หา "วันที่" ทุกจุดในหน้า (รองรับทั้ง "13 ก.ค. 2569" และ "13/7/69")
    # แล้วอ่านผลรางวัลเฉพาะช่วงข้อความก่อนถึงวันที่ถัดไป กันข้อมูลข้ามงวดปนกัน
    dates = []  # (pos_start, pos_end, iso)
    for m in DATE_RE.finditer(text):
        iso = to_iso(int(m.group(1)), TH_MONTHS[m.group(2)], int(m.group(3)))
        if iso:
            dates.append((m.start(), m.end(), iso))
    for m in DATE_NUM_RE.finditer(text):
        day, mon, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mon <= 12:
            iso = to_iso(day, mon, year)
            if iso:
                dates.append((m.start(), m.end(), iso))
    dates.sort()

    for j, (s, e, iso) in enumerate(dates):
        win_end = dates[j + 1][0] if j + 1 < len(dates) else e + 250
        window = text[e: min(win_end, e + 250)]
        n4m = N4_RE.search(window)
        if not n4m:
            continue
        low2m = LOW2_RE.search(window)
        results.append(make_record(iso, n4m.group(1),
                                   low2m.group(1) if low2m else None))
    return results


def make_record(iso: str, n4: str, low2: str | None) -> dict:
    return {
        "date": iso,
        "n4": n4,
        "top3": n4[1:],
        "top2": n4[2:],
        # บางแหล่งไม่มี 2 ตัวล่าง -> เก็บ null ไว้ หน้าเว็บจะข้ามให้เอง
        "low2": low2,
    }


def fetch(url: str) -> str | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = r.apparent_encoding  # เว็บไทยเก่าบางเว็บเป็น TIS-620
        return r.text
    except requests.RequestException as e:
        print(f"  [ข้าม] ดึงไม่สำเร็จ: {url} ({e})", file=sys.stderr)
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merge", help="ไฟล์ results.json เดิมที่จะรวมข้อมูลเข้าด้วยกัน")
    ap.add_argument("--out", default="results.json")
    args = ap.parse_args()

    all_records: dict[str, dict] = {}

    # โหลดของเดิม (ทำให้รันซ้ำเพื่ออัปเดตงวดใหม่ได้ ไม่ต้องดึงใหม่หมด)
    if args.merge and Path(args.merge).exists():
        for rec in json.loads(Path(args.merge).read_text(encoding="utf-8")):
            all_records[rec["date"]] = rec
        print(f"โหลดข้อมูลเดิม {len(all_records)} งวด จาก {args.merge}")

    for url in SOURCES:
        print(f"กำลังดึง: {url}")
        html = fetch(url)
        if not html:
            continue
        recs = parse_page(html)
        new = 0
        for rec in recs:
            if rec["date"] not in all_records:
                new += 1
            # ข้อมูลใหม่ทับของเก่าเฉพาะเมื่อมี low2 ครบกว่า
            old = all_records.get(rec["date"])
            if old is None or (old.get("low2") is None and rec.get("low2")):
                all_records[rec["date"]] = rec
        print(f"  พบ {len(recs)} งวด (ใหม่ {new})")
        time.sleep(DELAY_SEC)

    out = sorted(all_records.values(), key=lambda r: r["date"])
    Path(args.out).write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nบันทึก {len(out)} งวด -> {args.out}")
    if out:
        print(f"ช่วงข้อมูล: {out[0]['date']} ถึง {out[-1]['date']}")
        print("ตัวอย่าง 3 งวดล่าสุด:")
        for r in out[-3:]:
            print(" ", r)
    print("\n*** อย่าลืมสุ่มตรวจผลลัพธ์เทียบกับเว็บจริงก่อนใช้ ***")


if __name__ == "__main__":
    main()
