#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""يفعّل مصادر Jooble بعد ما تجيب المفتاح المجاني من jooble.org/api/about
   python enable_jooble.py          تفعيل
   python enable_jooble.py --off    تعطيل
"""
import json, sys
from pathlib import Path
on = "--off" not in sys.argv
p = Path("sources.json"); d = json.loads(p.read_text(encoding="utf-8"))
n = sum(1 for s in d if s.get("kind") == "jooble")
for s in d:
    if s.get("kind") == "jooble":
        s["is_active"] = on
p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"{'تفعيل' if on else 'تعطيل'} {n} مصدر Jooble.")
