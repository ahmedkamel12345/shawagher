#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""يضم وظائف واتساب اليدوية (manual.json) لملف jobs.json الرئيسي.

    python merge_manual.py                       # يضم manual.json إلى jobs.json
    python merge_manual.py --jobs ../web/data/jobs.json

الوظائف اليدوية بتتخزن كمان في manual_store.json عشان متضيعش
لما تشغّل fetch_jobs.py تاني — كل مرة بيتضموا من جديد.
"""
import argparse
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path


def fingerprint(company, title, city):
    norm = lambda s: re.sub(r"[^a-z0-9\u0600-\u06FF]+", "", (s or "").lower())  # noqa: E731
    return hashlib.sha1("|".join([norm(company), norm(title), norm(city)]).encode()).hexdigest()


MAX_AGE_DAYS = 30   # الإعلانات الأقدم من كده بتتحذف تلقائياً


def fresh(j, cutoff):
    try:
        d = datetime.fromisoformat((j.get("posted_at") or "").replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d >= cutoff
    except ValueError:
        return True          # من غير تاريخ = نسيبه


ap = argparse.ArgumentParser()
ap.add_argument("--manual", default="manual.json")
ap.add_argument("--jobs", default="jobs.json")
ap.add_argument("--store", default="manual_store.json")
a = ap.parse_args()

store_path = Path(a.store)
store = json.loads(store_path.read_text(encoding="utf-8")) if store_path.exists() else []
before = len(store)
_cut = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
store = [j for j in store if fresh(j, _cut)]

manual_path = Path(a.manual)
if not manual_path.exists():
    store_path.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
if manual_path.exists():
    incoming = json.loads(manual_path.read_text(encoding="utf-8")).get("jobs", [])
    seen = {j["fingerprint"] for j in store}
    incoming = [j for j in incoming if fresh(j, _cut)]
    for j in incoming:
        j["fingerprint"] = fingerprint(j.get("company_name"), j.get("title"), j.get("city"))
        j.setdefault("source_kind", "whatsapp")
        j.setdefault("is_direct", True)
        if j["fingerprint"] not in seen:
            store.append(j)
            seen.add(j["fingerprint"])
    store_path.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"إعلانات واتساب: {before} + {len(store)-before} جديد = {len(store)}")
else:
    print(f"مفيش {a.manual} — هيتم ضم المخزّن فقط ({len(store)})")

jobs_path = Path(a.jobs)
if not jobs_path.exists():
    raise SystemExit(f"مش لاقي {a.jobs} — شغّل fetch_jobs.py الأول")

data = json.loads(jobs_path.read_text(encoding="utf-8"))
jobs = [j for j in data.get("jobs", []) if j.get("source_kind") != "whatsapp" and fresh(j, _cut)]
have = {j["fingerprint"] for j in jobs}
added = [j for j in store if j["fingerprint"] not in have]

jobs = added + jobs                       # الإعلانات المباشرة تظهر الأول
data["jobs"] = jobs
data["count"] = len(jobs)
data["generated_at"] = datetime.now(timezone.utc).isoformat()
data.pop("demo", None)
jobs_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"تم: {len(added)} إعلان واتساب + {len(jobs)-len(added)} من المصادر = {len(jobs)} في {a.jobs}")

# توليد منشورات واتساب الجاهزة للنسخ (اختياري — بيتخطى لو الملف مش موجود)
try:
    import subprocess, sys
    _mk = Path(__file__).with_name("make_wa_post.py")
    if _mk.exists():
        subprocess.run([sys.executable, str(_mk), "--jobs", str(jobs_path)], check=False)
except Exception as _e:  # noqa: BLE001
    print("تخطّي منشور واتساب:", _e)
