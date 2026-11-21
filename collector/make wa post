#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""يولّد منشورات واتساب جاهزة للنسخ (واحد لكل بلد) من أحدث الوظائف.

    python make_wa_post.py --jobs ../web/data/jobs.json

الناتج جنب jobs.json:
    whatsapp_post.json   (نص كل بلد + رابط الجروب)  -> بتقراه صفحة wa-post.html
    whatsapp_post.txt    (نفس النصوص في ملف واحد للنسخ اليدوي)
"""
import argparse
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

SITE = "https://shawagherna.com/"
PER_COUNTRY = 8          # أقصى عدد وظايف في المنشور
WINDOW_DAYS = 3          # بنفضّل وظايف آخر ٣ أيام
COUNTRIES = [("KW", "🇰🇼", "الكويت"), ("EG", "🇪🇬", "مصر"), ("SA", "🇸🇦", "السعودية")]


def parse_dt(s):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def clean(s, n=70):
    s = re.sub(r"\s+", " ", (s or "")).strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def contact_line(j):
    url = (j.get("apply_url") or "").strip()
    if url.lower().startswith("http"):
        return "🔗 قدّم: " + url
    m = re.search(r"(\+?\d[\d\s-]{7,15}\d)", (j.get("apply_url") or "") + " " + (j.get("summary") or ""))
    if m:
        return "📞 للتواصل: " + re.sub(r"[\s-]", "", m.group(1))
    return ""


def job_block(j, n):
    lines = [f"{n}️⃣ *{clean(j.get('title'))}*"] if n <= 9 else [f"▪️ *{clean(j.get('title'))}*"]
    where = " - ".join(x for x in [clean(j.get("company_name"), 40), clean(j.get("city"), 25)] if x)
    if where:
        lines.append("🏢 " + where)
    c = contact_line(j)
    if c:
        lines.append(c)
    return "\n".join(lines)


def build(jobs, flag, name, group_url):
    head = f"{flag} *وظائف {name} الجديدة* — شواغر\n"
    body = "\n\n".join(job_block(j, i) for i, j in enumerate(jobs, 1))
    foot = (
        f"\n\n🌐 كل الوظايف والتقديم: {SITE}\n"
        f"👥 انضم لجروب {name}: {group_url}" if group_url else f"\n\n🌐 كل الوظايف والتقديم: {SITE}"
    )
    return head + "\n" + body + foot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", default="jobs.json")
    ap.add_argument("--groups", default="")
    ap.add_argument("--n", type=int, default=PER_COUNTRY)
    a = ap.parse_args()

    jp = Path(a.jobs)
    data = json.loads(jp.read_text(encoding="utf-8"))
    jobs = data.get("jobs", [])
    gp = Path(a.groups) if a.groups else jp.with_name("groups.json")
    gurls = {}
    if gp.exists():
        for g in json.loads(gp.read_text(encoding="utf-8")).get("groups", []):
            if g.get("kind") == "jobs" and g.get("country"):
                gurls[g["country"]] = g.get("url", "")

    cutoff = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "site": SITE, "posts": []}
    txt = []
    for code, flag, name in COUNTRIES:
        mine = [j for j in jobs if j.get("country") == code]
        mine.sort(key=lambda j: j.get("posted_at") or "", reverse=True)
        recent = [j for j in mine if (parse_dt(j.get("posted_at")) or cutoff - timedelta(days=1)) >= cutoff]
        pick = (recent or mine)[: a.n]
        if not pick:
            continue
        text = build(pick, flag, name, gurls.get(code, ""))
        out["posts"].append({"country": code, "flag": flag, "name": name,
                             "count": len(pick), "group_url": gurls.get(code, ""), "text": text})
        txt.append(f"======== {flag} {name} ({len(pick)}) ========\n{text}\n")

    jp.with_name("whatsapp_post.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    jp.with_name("whatsapp_post.txt").write_text("\n".join(txt), encoding="utf-8")
    print(f"منشورات واتساب: {', '.join(p['name'] + '=' + str(p['count']) for p in out['posts']) or 'لا يوجد'}")


if __name__ == "__main__":
    main()
