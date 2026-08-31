#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
شواغر — مكتشف إعلانات الأفراد
==============================
يجمع إعلانات الوظائف المنشورة من أفراد (مش من مواقع التوظيف التجارية)
عبر ثلاث قنوات مشروعة، كلها بتدي عنوان + ملخص قصير + رابط المصدر:

  ١) Google Alerts RSS   — بدون مفتاح. تعمل تنبيه على جوجل بصيغة RSS وتحط رابطه هنا.
  ٢) Google CSE          — واجهة البحث الرسمية (١٠٠ استعلام مجاني يومياً).
  ٣) قنوات تليجرام العامة — صفحة المعاينة العامة t.me/s/<channel>.

المخرجات: discovered.json بنفس صيغة jobs.json، وبتتضم بـ merge_manual.py.

التشغيل:
    pip install requests
    python discover.py --config discover.json --out .

متغيرات البيئة (اختيارية):
    GOOGLE_API_KEY, GOOGLE_CSE_ID     لتفعيل البحث عبر Google CSE

ملاحظات مهمة:
- بنخزّن ملخص قصير (≤٢٤٠ حرف) + رابط المصدر الأصلي. مفيش نسخ لإعلان كامل.
- فيسبوك وإنستجرام وواتساب مش هنا: قراءتها آلياً مخالفة لشروط استخدامها.
  البديل الشرعي ليها أداة whatsapp-import.html والنشر المباشر من الموقع.
- كل إعلان بيعدّي على فلتر نصب (رسوم، تأشيرات مدفوعة، أرباح خيالية) قبل ما يتقبل.
"""

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import requests

UA = "ShawagherBot/1.0 (+https://shawagherna.netlify.app)"
TIMEOUT = 25
SLEEP = 1.0

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")

# ------------------------------------------------------------------
# الجودة: نقبل إعلانات وظائف حقيقية فقط
# ------------------------------------------------------------------
JOB_SIGNALS = ["مطلوب", "نبحث عن", "فرصة عمل", "وظيفة", "شاغر", "وظائف", "تعلن", "للتعيين",
               "يتطلب", "hiring", "vacancy", "we are looking", "job opening", "recruiting"]

SCAM_SIGNALS = ["رسوم", "مبلغ رمزي", "تحويل مبلغ", "ادفع", "مقابل مادي للتقديم", "عمولة تقديم",
                "ربح من المنزل", "دخل خيالي", "استثمار", "تداول", "فوركس", "شحن رصيد",
                "كاش باك", "تسويق شبكي", "بيتكوين", "كريبتو", "registration fee", "pay to apply"]

BLOCK_HOSTS = ["linkedin.com", "indeed.com", "bayt.com", "glassdoor.com", "naukri", "monster.com",
               "facebook.com", "instagram.com", "wuzzuf.net", "gulftalent.com"]

COUNTRY_PATTERNS = {
    "KW": ["الكويت", "kuwait", "حولي", "السالمية", "الفروانية", "الجهراء", "الأحمدي", "الفحيحيل"],
    "SA": ["السعودية", "saudi", "الرياض", "جدة", "الدمام", "الخبر", "مكة", "المدينة"],
    "AE": ["الإمارات", "uae", "دبي", "أبوظبي", "الشارقة", "عجمان", "العين"],
    "QA": ["قطر", "qatar", "الدوحة"],
    "BH": ["البحرين", "bahrain", "المنامة"],
    "OM": ["عمان", "oman", "مسقط", "صلالة"],
    "EG": ["مصر", "egypt", "القاهرة", "الجيزة", "الإسكندرية", "المعادي", "مدينة نصر", "أكتوبر"],
}

CATEGORY_RULES = [
    ("accounting", ["محاسب", "محاسبة", "مالي", "مدقق", "مراجع", "ضريب", "accountant", "finance"]),
    ("it",         ["مبرمج", "مطور", "برمج", "شبكات", "دعم فني", "odoo", "أودو", "developer", "software"]),
    ("sales",      ["مبيعات", "مندوب", "تسويق", "سيلز", "sales", "marketing"]),
    ("hr",         ["موارد بشرية", "شؤون موظفين", "توظيف", "hr", "recruit"]),
    ("ops",        ["مخازن", "مخزن", "لوجستي", "تشغيل", "إنتاج", "warehouse", "logistics"]),
    ("service",    ["خدمة عملاء", "كول سنتر", "كاشير", "استقبال", "مضيف", "بائع", "customer service"]),
    ("health",     ["طبيب", "ممرض", "صيدل", "أخصائي علاج", "مختبر", "nurse", "pharmac"]),
    ("education",  ["معلم", "مدرس", "مدرّس", "أكاديمي", "teacher", "tutor"]),
]

SENIORITY_RULES = [
    ("executive", ["مدير عام", "رئيس تنفيذي", "general manager", "ceo"]),
    ("manager",   ["مدير", "رئيس قسم", "manager", "head of"]),
    ("supervisor",["مشرف", "ملاحظ", "supervisor", "team lead"]),
    ("senior",    ["أول", "خبير", "استشاري", "senior"]),
    ("entry",     ["حديث التخرج", "مبتدئ", "متدرب", "خريج", "junior", "fresh"]),
    ("worker",    ["عامل", "عمال", "سائق", "حارس", "نظافة", "فني", "حرفي", "driver", "worker"]),
]


def clean(raw, limit=240):
    if not raw:
        return None
    txt = WS_RE.sub(" ", html.unescape(TAG_RE.sub(" ", str(raw)))).strip()
    return txt if len(txt) <= limit else txt[:limit].rsplit(" ", 1)[0] + "…"


def pick(text, rules, default=None):
    t = (text or "").lower()
    for value, keys in rules:
        if any(k.lower() in t for k in keys):
            return value
    return default


def detect_country(text):
    t = (text or "").lower()
    for code, keys in COUNTRY_PATTERNS.items():
        if any(k.lower() in t for k in keys):
            return code
    return None


def detect_city(text, country):
    """يفضّل اسم المدينة على اسم الدولة (أول عنصرين في القائمة اسم الدولة)."""
    names = COUNTRY_PATTERNS.get(country or "", [])
    cities = [c for c in names[2:] if not c.islower()]
    for c in cities:
        if c in (text or ""):
            return c
    for c in names[:2]:
        if not c.islower() and c in (text or ""):
            return c
    return None


def clean_title(text):
    line = (text or "").split("\n")[0].strip()
    line = re.sub(r"^[\-–•*#\s]+", "", line)
    line = re.sub(r"(مطلوب للعمل|مطلوب فورا|مطلوب فوراً|مطلوب|نبحث عن|فرصة عمل|وظيفة شاغرة|وظائف|شاغر)\s*[:\-–]?\s*",
                  "", line, flags=re.I)
    return re.sub(r"\s*[|\-–]\s*(وظائف|jobs?)\b.*$", "", line, flags=re.I).strip()[:90] or "وظيفة"


def is_job_ad(text):
    """يقبل الإعلان لو فيه إشارة توظيف وميكونش فيه إشارة نصب."""
    t = (text or "").lower()
    if not any(s.lower() in t for s in JOB_SIGNALS):
        return False, "مش إعلان وظيفة"
    hit = next((s for s in SCAM_SIGNALS if s.lower() in t), None)
    if hit:
        return False, f"مشتبه به: {hit}"
    return True, ""


def blocked(url):
    u = (url or "").lower()
    return any(h in u for h in BLOCK_HOSTS)


def fingerprint(*parts):
    norm = "|".join(re.sub(r"[^a-z0-9\u0600-\u06FF]+", "", (p or "").lower()) for p in parts)
    return hashlib.sha1(norm.encode()).hexdigest()


def make(title, body, url, source, posted=None):
    text = f"{title}\n{body or ''}"
    country = detect_country(text)
    t = clean_title(title)
    return {
        "fingerprint": fingerprint(source, t, country),
        "title": t,
        "company_name": "إعلان منشور",
        "city": detect_city(text, country),
        "country": country,
        "category": pick(text, CATEGORY_RULES, "other"),
        "seniority": pick(text, SENIORITY_RULES, "mid"),
        "employment_type": "full_time",
        "is_remote": bool(re.search(r"عن بعد|عن بُعد|remote|من المنزل", text, re.I)),
        "summary": clean(body or title),
        "apply_url": url,
        "source_kind": "discover",
        "source_name": source,
        "posted_at": posted or datetime.now(timezone.utc).isoformat(),
        "is_direct": False,
        "needs_review": True,
    }


# ------------------------------------------------------------------
# ١) Google Alerts RSS — بدون مفتاح
#    إزاي تعملها: google.com/alerts ← اكتب الاستعلام ← Show options
#    ← Deliver to: RSS feed ← Create Alert ← انسخ رابط الـ RSS
# ------------------------------------------------------------------
def from_alerts(feed_url, source="google-alerts"):
    r = requests.get(feed_url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for e in root.findall(".//a:entry", ns) or root.findall(".//item"):
        get = lambda tag: (e.findtext(f"a:{tag}", namespaces=ns) or e.findtext(tag) or "")  # noqa: E731
        link_el = e.find("a:link", ns)
        url = (link_el.get("href") if link_el is not None else get("link")) or ""
        m = re.search(r"[?&]url=([^&]+)", url)          # جوجل بيلف الروابط
        if m:
            from urllib.parse import unquote
            url = unquote(m.group(1))
        title, body = clean(get("title"), 200), clean(get("content") or get("summary"))
        if not (title and url) or blocked(url):
            continue
        ok, _ = is_job_ad(f"{title} {body}")
        if not ok:
            continue
        out.append(make(title, body, url, source, get("published") or None))
    return out


# ------------------------------------------------------------------
# ٢) Google Programmable Search (CSE) — ١٠٠ استعلام مجاني يومياً
#    جهّزه من programmablesearchengine.google.com ثم فعّل Custom Search API
# ------------------------------------------------------------------
def from_cse(query, country=None, pages=2):
    key, cx = os.getenv("GOOGLE_API_KEY"), os.getenv("GOOGLE_CSE_ID")
    if not (key and cx):
        raise RuntimeError("محتاج GOOGLE_API_KEY و GOOGLE_CSE_ID")
    out = []
    for page in range(pages):
        r = requests.get("https://www.googleapis.com/customsearch/v1", timeout=TIMEOUT, params={
            "key": key, "cx": cx, "q": query, "num": 10, "start": 1 + page * 10,
            "dateRestrict": "d3", "lr": "lang_ar",
        })
        if r.status_code == 429:
            print("  حصة Google CSE خلصت لليوم", file=sys.stderr)
            break
        r.raise_for_status()
        items = r.json().get("items", [])
        for it in items:
            url, title, body = it.get("link", ""), clean(it.get("title"), 200), clean(it.get("snippet"))
            if blocked(url):
                continue
            ok, _ = is_job_ad(f"{title} {body}")
            if not ok:
                continue
            j = make(title, body, url, "google-search")
            if country and not j["country"]:
                j["country"] = country
            out.append(j)
        if len(items) < 10:
            break
        time.sleep(SLEEP)
    return out


# ------------------------------------------------------------------
# ٣) قنوات تليجرام العامة — صفحة المعاينة المتاحة للجميع
# ------------------------------------------------------------------
POST_RE = re.compile(
    r'data-post="(?P<ch>[^/]+)/(?P<id>\d+)".*?'
    r'<div class="tgme_widget_message_text[^"]*"[^>]*>(?P<body>.*?)</div>', re.S)


def from_telegram(channel, source=None):
    r = requests.get(f"https://t.me/s/{channel}", headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for m in POST_RE.finditer(r.text):
        body = clean(m.group("body").replace("<br/>", "\n"), 600)
        if not body:
            continue
        ok, _ = is_job_ad(body)
        if not ok:
            continue
        url = f"https://t.me/{m.group('ch')}/{m.group('id')}"
        out.append(make(body.split("\n")[0][:120], body, url, source or f"telegram:{channel}"))
    return out


# ------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="discover.json")
    ap.add_argument("--out", default=".")
    ap.add_argument("--all-countries", action="store_true")
    a = ap.parse_args()

    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    raw, report = [], []

    for f in cfg.get("google_alerts", []):
        if not f.get("is_active", True):
            continue
        try:
            got = from_alerts(f["url"], f.get("name", "google-alerts"))
            raw += got
            report.append(("alerts", f.get("name", ""), len(got), "ok"))
        except Exception as e:                                    # noqa: BLE001
            report.append(("alerts", f.get("name", ""), 0, f"{type(e).__name__}: {e}"[:90]))
        time.sleep(SLEEP)

    for q in cfg.get("google_search", []):
        if not q.get("is_active", True):
            continue
        try:
            got = from_cse(q["query"], q.get("country"), int(q.get("pages", 2)))
            raw += got
            report.append(("cse", q["query"], len(got), "ok"))
        except Exception as e:                                    # noqa: BLE001
            report.append(("cse", q.get("query", ""), 0, f"{type(e).__name__}: {e}"[:90]))
        time.sleep(SLEEP)

    for t in cfg.get("telegram", []):
        if not t.get("is_active", True):
            continue
        try:
            got = from_telegram(t["channel"], t.get("name"))
            raw += got
            report.append(("telegram", t["channel"], len(got), "ok"))
        except Exception as e:                                    # noqa: BLE001
            report.append(("telegram", t.get("channel", ""), 0, f"{type(e).__name__}: {e}"[:90]))
        time.sleep(SLEEP)

    for kind, name, n, st in report:
        print(f"[{st[:28]:>28}] {kind:<9} {name[:34]:<34} {n:>4}", file=sys.stderr)

    geo = raw if a.all_countries else [j for j in raw if j["country"]]
    seen, jobs = set(), []
    for j in geo:
        if j["fingerprint"] in seen or not j["apply_url"]:
            continue
        seen.add(j["fingerprint"])
        jobs.append(j)
    jobs.sort(key=lambda x: x["posted_at"], reverse=True)

    out_dir = Path(a.out); out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "discovered.json").write_text(
        json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(),
                    "count": len(jobs), "jobs": jobs}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"\nالخام {len(raw)} → بعد الفلتر الجغرافي {len(geo)} → بعد إزالة المكرر {len(jobs)}", file=sys.stderr)
    print(f"الملف: {out_dir/'discovered.json'}", file=sys.stderr)


if __name__ == "__main__":
    main()
