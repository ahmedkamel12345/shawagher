#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
يفحص كل مصدر في sources.json ويقول شغّال ولا لأ.

    python check_sources.py sources.json            # فحص فقط
    python check_sources.py sources.json --prune    # فحص + تعطيل الفاشل تلقائياً

--prune بيعمل نسخة احتياطية (sources.backup.json) وبيحوّل أي مصدر فاشل
لـ is_active: false بدل ما يمسحه، عشان تقدر ترجعه لو اتصلح بعدين.

إزاي تلاقي الـ slug لأي شركة — افتح صفحة وظائفها وشوف اللينك:
  greenhouse       boards.greenhouse.io/<slug>
  lever            jobs.lever.co/<slug>
  workable         apply.workable.com/<slug>
  smartrecruiters  jobs.smartrecruiters.com/<slug>
  recruitee        <slug>.recruitee.com
  ashby            jobs.ashbyhq.com/<slug>
  bamboohr         <slug>.bamboohr.com/careers
  personio         <slug>.jobs.personio.com
"""
import json
import sys
from pathlib import Path

from fetch_jobs import FETCHERS

path = Path(sys.argv[1] if len(sys.argv) > 1 else "sources.json")
prune = "--prune" in sys.argv

original = path.read_text(encoding="utf-8")
sources = json.loads(original)
live = [s for s in sources if "kind" in s and s.get("is_active", True)]

ok = 0
for src in live:
    fetcher = FETCHERS.get(src["kind"])
    label = f"{src['kind']:<16} {src.get('slug',''):<22} {src.get('company_name','')}"
    if not fetcher:
        print(f"X  {label}  -- نوع غير معروف")
        src["is_active"] = False
        continue
    try:
        jobs = fetcher(src)
        region = sum(1 for j in jobs if j["country"])
        print(f"OK {label}  -- {len(jobs)} وظيفة ({region} في المنطقة)")
        ok += 1
    except Exception as exc:                      # noqa: BLE001
        print(f"X  {label}  -- {type(exc).__name__}: {str(exc)[:70]}")
        src["is_active"] = False

print(f"\n{ok} من {len(live)} مصدر شغّال.")

if prune:
    Path("sources.backup.json").write_text(original, encoding="utf-8")
    path.write_text(json.dumps(sources, ensure_ascii=False, indent=1), encoding="utf-8")
    print("تم تعطيل المصادر الفاشلة. النسخة الأصلية محفوظة في sources.backup.json")
else:
    print("ضيف --prune عشان يعطّل الفاشل تلقائياً.")
