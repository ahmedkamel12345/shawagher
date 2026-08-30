#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""يفعّل كل مصادر Careerjet في sources.json (بعد ما تجيب المفتاح).
   python enable_careerjet.py            تفعيل
   python enable_careerjet.py --off      تعطيل
"""
import json, sys
from pathlib import Path

on = "--off" not in sys.argv
p = Path("sources.json")
d = json.loads(p.read_text(encoding="utf-8"))
n = 0
for s in d:
    if s.get("kind") == "careerjet":
        s["is_active"] = on
        n += 1
p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"{'تفعيل' if on else 'تعطيل'} {n} مصدر Careerjet.")
