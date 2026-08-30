#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
شواغر | Shawagher — مجمّع الشواغر اليومي
=========================================
يسحب الوظائف من بوردات التوظيف العامة (Greenhouse / Lever / Workable /
SmartRecruiters / Recruitee) ومن Careerjet API، يوحّد الحقول، يفلتر على
دول الخليج ومصر، يشيل المكرر، ويطلع:

    out/jobs.json        ملف جاهز للواجهة (static)
    out/report.json      تقرير التشغيل

واختيارياً يرفع النتيجة على Supabase.

التشغيل:
    pip install requests
    python fetch_jobs.py --sources sources.json --out ../web/data

متغيرات البيئة الاختيارية:
    SUPABASE_URL, SUPABASE_SERVICE_KEY   للرفع على قاعدة البيانات
    CAREERJET_AFFID                      لتفعيل مصدر Careerjet

ملاحظة قانونية: السكريبت ده بيستخدم واجهات عامة معلن عنها من مزوّدي ATS.
ما بيعملش scraping للينكدإن أو إنديد أو بيت — ده مخالف لشروط استخدامهم.
بنخزّن ملخص قصير + رابط المصدر، والتقديم بيتم على الموقع الأصلي.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

import requests

UA = "ShawagherBot/1.0 (+https://shawagher.com/bot)"
TIMEOUT = 25
SLEEP_BETWEEN = 0.7  # تهدئة بين الطلبات

# ------------------------------------------------------------------
# فلتر الدول: الخليج + مصر
# ------------------------------------------------------------------
COUNTRY_PATTERNS = {
    "KW": ["kuwait", "الكويت", "kwt", "hawally", "salmiya", "farwaniya", "ahmadi", "jahra"],
    "SA": ["saudi", "ksa", "السعودية", "riyadh", "الرياض", "jeddah", "جدة", "dammam", "khobar", "mecca", "medina", "neom"],
    "AE": ["united arab emirates", "uae", "الإمارات", "dubai", "دبي", "abu dhabi", "أبوظبي", "sharjah", "الشارقة", "ajman"],
    "QA": ["qatar", "قطر", "doha", "الدوحة"],
    "BH": ["bahrain", "البحرين", "manama", "المنامة"],
    "OM": ["oman", "عمان", "muscat", "مسقط"],
    "EG": ["egypt", "مصر", "cairo", "القاهرة", "giza", "الجيزة", "alexandria", "الإسكندرية", "maadi", "nasr city", "new cairo", "6th of october"],
}

CATEGORY_RULES = [
    ("accounting", ["accountant", "accounting", "finance", "audit", "محاسب", "مالية", "مدقق", "treasury", "payable", "receivable"]),
    ("it",         ["developer", "engineer", "software", "data", "devops", "it ", "برمج", "مطور", "شبكات", "security", "qa engineer"]),
    ("sales",      ["sales", "business development", "account manager", "مبيعات", "مندوب", "تسويق", "marketing", "merchandiser"]),
    ("hr",         ["human resources", "recruit", "talent", "موارد بشرية", "توظيف", "payroll"]),
    ("ops",        ["operations", "logistics", "supply chain", "warehouse", "driver", "تشغيل", "مخازن", "لوجستي", "سائق"]),
    ("health",     ["nurse", "physician", "doctor", "pharmac", "طبيب", "ممرض", "صيدل", "مختبر"]),
    ("education",  ["teacher", "instructor", "tutor", "معلم", "مدرس", "أكاديمي"]),
    ("service",    ["customer service", "call center", "cashier", "waiter", "barista", "خدمة عملاء", "كاشير", "مضيف", "استقبال"]),
]

SENIORITY_RULES = [
    ("manager", ["manager", "head of", "director", "chief", "مدير", "رئيس"]),
    ("senior",  ["senior", "sr.", "lead", "principal", "أول", "خبير"]),
    ("entry",   ["junior", "jr.", "intern", "trainee", "graduate", "fresh", "مبتدئ", "متدرب", "حديث"]),
]

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


# ------------------------------------------------------------------
# أدوات مساعدة
# ------------------------------------------------------------------
def clean_text(raw, limit=280):
    """ملخص قصير فقط — مش نسخ للإعلان كامل (حقوق نشر + محتوى مكرر)."""
    if not raw:
        return None
    txt = WS_RE.sub(" ", unescape(TAG_RE.sub(" ", str(raw)))).strip()
    if len(txt) <= limit:
        return txt
    cut = txt[:limit].rsplit(" ", 1)[0]
    return cut + "…"


def detect_country(*chunks):
    blob = " ".join([c for c in chunks if c]).lower()
    for code, needles in COUNTRY_PATTERNS.items():
        for n in needles:
            if n in blob:
                return code
    return None


def detect_city(location, country):
    if not location:
        return None
    loc = location.split(",")[0].strip()
    return loc[:60] or None


def classify(title, key, rules, default=None):
    t = (title or "").lower()
    for value, needles in rules:
        if any(n in t for n in needles):
            return value
    return default


def fingerprint(company, title, city):
    base = "|".join([
        re.sub(r"[^a-z0-9\u0600-\u06FF]+", "", (company or "").lower()),
        re.sub(r"[^a-z0-9\u0600-\u06FF]+", "", (title or "").lower()),
        re.sub(r"[^a-z0-9\u0600-\u06FF]+", "", (city or "").lower()),
    ])
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def iso(dt_value):
    if not dt_value:
        return None
    if isinstance(dt_value, (int, float)):
        # Lever/Workable بيرجعوا ملي ثانية
        val = dt_value / 1000 if dt_value > 1e11 else dt_value
        return datetime.fromtimestamp(val, tz=timezone.utc).isoformat()
    s = str(dt_value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s).astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def iso_rfc(value):
    """Careerjet بيرجع التاريخ بصيغة: Wed,15 Nov 2025 19:13:43 GMT"""
    if not value:
        return None
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(str(value).replace(",", ", ", 1)).astimezone(timezone.utc).isoformat()
    except Exception:
        return iso(value)


def get_json(url, params=None):
    r = requests.get(url, params=params, headers={"User-Agent": UA, "Accept": "application/json"}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def make_job(**kw):
    title = kw.get("title")
    company = kw.get("company_name")
    location = kw.get("location")
    country = kw.get("country") or detect_country(location, kw.get("summary"))
    city = detect_city(location, country)
    return {
        "fingerprint": fingerprint(company, title, city),
        "title": title,
        "company_name": company,
        "city": city,
        "country": country,
        "location_raw": location,
        "category": classify(title, "category", CATEGORY_RULES, "other"),
        "seniority": classify(title, "seniority", SENIORITY_RULES, "mid"),
        "employment_type": kw.get("employment_type") or "full_time",
        "is_remote": bool(kw.get("is_remote")),
        "summary": kw.get("summary"),
        "apply_url": kw.get("apply_url"),
        "source_kind": kw.get("source_kind"),
        "source_slug": kw.get("source_slug"),
        "posted_at": kw.get("posted_at"),
    }


# ------------------------------------------------------------------
# المصادر — كلها واجهات عامة موثّقة
# ------------------------------------------------------------------
def from_greenhouse(src):
    data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{src['slug']}/jobs", {"content": "true"})
    out = []
    for j in data.get("jobs", []):
        out.append(make_job(
            title=j.get("title"),
            company_name=src["company_name"],
            location=(j.get("location") or {}).get("name"),
            summary=clean_text(j.get("content")),
            apply_url=j.get("absolute_url"),
            posted_at=iso(j.get("updated_at")),
            source_kind="greenhouse", source_slug=src["slug"],
        ))
    return out


def from_lever(src):
    data = get_json(f"https://api.lever.co/v0/postings/{src['slug']}", {"mode": "json"})
    out = []
    for j in data:
        cats = j.get("categories") or {}
        out.append(make_job(
            title=j.get("text"),
            company_name=src["company_name"],
            location=cats.get("location"),
            employment_type=(cats.get("commitment") or "").lower().replace(" ", "_") or None,
            summary=clean_text(j.get("descriptionPlain") or j.get("description")),
            apply_url=j.get("hostedUrl"),
            posted_at=iso(j.get("createdAt")),
            source_kind="lever", source_slug=src["slug"],
        ))
    return out


def from_workable(src):
    data = get_json(f"https://apply.workable.com/api/v1/widget/accounts/{src['slug']}")
    out = []
    for j in data.get("jobs", []):
        loc = ", ".join(x for x in [j.get("city"), j.get("country")] if x)
        out.append(make_job(
            title=j.get("title"),
            company_name=src["company_name"],
            location=loc,
            summary=clean_text(j.get("description")),
            apply_url=j.get("url") or j.get("application_url"),
            posted_at=iso(j.get("published_on")),
            is_remote=bool(j.get("telecommuting")),
            source_kind="workable", source_slug=src["slug"],
        ))
    return out


def from_smartrecruiters(src):
    out, offset = [], 0
    while True:
        data = get_json(f"https://api.smartrecruiters.com/v1/companies/{src['slug']}/postings",
                        {"limit": 100, "offset": offset})
        items = data.get("content", [])
        for j in items:
            loc = j.get("location") or {}
            location = ", ".join(x for x in [loc.get("city"), loc.get("country")] if x)
            out.append(make_job(
                title=j.get("name"),
                company_name=src["company_name"],
                location=location,
                is_remote=bool(loc.get("remote")),
                apply_url=f"https://jobs.smartrecruiters.com/{src['slug']}/{j.get('id')}",
                posted_at=iso(j.get("releasedDate")),
                source_kind="smartrecruiters", source_slug=src["slug"],
            ))
        offset += len(items)
        if len(items) < 100 or offset > 500:
            break
        time.sleep(SLEEP_BETWEEN)
    return out


def from_recruitee(src):
    data = get_json(f"https://{src['slug']}.recruitee.com/api/offers/")
    out = []
    for j in data.get("offers", []):
        loc = ", ".join(x for x in [j.get("city"), j.get("country")] if x)
        out.append(make_job(
            title=j.get("title"),
            company_name=src["company_name"],
            location=loc,
            employment_type=(j.get("employment_type") or "").lower() or None,
            summary=clean_text(j.get("description")),
            apply_url=j.get("careers_url") or j.get("careers_apply_url"),
            posted_at=iso(j.get("published_at")),
            source_kind="recruitee", source_slug=src["slug"],
        ))
    return out


def _cj_request(endpoint, params, headers):
    r = requests.get(endpoint, params=params, headers=headers, timeout=TIMEOUT)
    if r.status_code == 400 and "locale" in r.text.lower():
        return {"type": "BAD_LOCALE"}
    r.raise_for_status()
    return r.json()


def from_careerjet(src):
    """Careerjet — النسخة v4 بمفتاح API، أو النسخة القديمة بـ affid.
       سجّل مجاناً من careerjet.com/partners/api
    """
    api_key = os.getenv("CAREERJET_API_KEY")
    affid = os.getenv("CAREERJET_AFFID")
    if not (api_key or affid):
        raise RuntimeError("محتاج CAREERJET_API_KEY أو CAREERJET_AFFID")

    site = src.get("site_url", "https://shawagherak.netlify.app")
    headers = {"User-Agent": UA, "Accept": "application/json", "Referer": site}
    locale = src.get("locale_code", "ar_KW")

    if api_key:
        import base64
        headers["Authorization"] = "Basic " + base64.b64encode(f"{api_key}:".encode()).decode()
        endpoint = "https://search.api.careerjet.net/v4/query"
        params = {"locale_code": locale, "keywords": src.get("keywords", ""),
                  "location": src.get("location", ""), "page_size": 100, "sort": "date",
                  "user_ip": "1.1.1.1", "user_agent": UA}
    else:
        endpoint = "https://public.api.careerjet.net/search"
        params = {"locale_code": locale, "keywords": src.get("keywords", ""),
                  "location": src.get("location", ""), "pagesize": 99, "sort": "date",
                  "affid": affid, "user_ip": "1.1.1.1", "user_agent": UA, "url": site}

    out, page, max_pages = [], 1, int(src.get("pages", 3))
    while page <= max_pages:
        params["page"] = page
        data = _cj_request(endpoint, params, headers)

        # لغة غير مدعومة → جرّب الإنجليزي لنفس الدولة
        if data.get("type") == "BAD_LOCALE" and locale.startswith("ar_"):
            locale = "en_" + locale.split("_")[1]
            params["locale_code"] = locale
            data = _cj_request(endpoint, params, headers)
        # موقع غامض → أعد البحث على مستوى الدولة كلها
        if data.get("type") == "LOCATIONS":
            if params.get("location"):
                params["location"] = ""
                data = _cj_request(endpoint, params, headers)
            else:
                break
        if data.get("type") != "JOBS":
            break

        jobs = data.get("jobs", [])
        for j in jobs:
            out.append(make_job(
                title=j.get("title"),
                company_name=j.get("company") or "غير محدد",
                location=j.get("locations"),
                summary=clean_text(j.get("description")),
                apply_url=j.get("url"),
                posted_at=iso_rfc(j.get("date")),
                country=src.get("country"),
                source_kind="careerjet", source_slug=src.get("slug", "careerjet"),
            ))
        if not jobs or page >= min(max_pages, int(data.get("pages", 1))):
            break
        page += 1
        time.sleep(SLEEP_BETWEEN)
    return out


def from_ashby(src):
    data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{src['slug']}")
    out = []
    for j in data.get("jobs", []):
        out.append(make_job(
            title=j.get("title"),
            company_name=src["company_name"],
            location=j.get("location"),
            employment_type=(j.get("employmentType") or "").lower() or None,
            summary=clean_text(j.get("descriptionPlain")),
            apply_url=j.get("jobUrl"),
            posted_at=iso(j.get("publishedAt")),
            is_remote=bool(j.get("isRemote")),
            source_kind="ashby", source_slug=src["slug"],
        ))
    return out


def from_bamboohr(src):
    data = get_json(f"https://{src['slug']}.bamboohr.com/careers/list")
    out = []
    for j in data.get("result", []):
        loc = j.get("location") or {}
        location = ", ".join(x for x in [loc.get("city"), loc.get("country")] if x)
        out.append(make_job(
            title=j.get("jobOpeningName"),
            company_name=src["company_name"],
            location=location or j.get("atsLocation"),
            employment_type=(j.get("employmentStatusLabel") or "").lower().replace(" ", "_") or None,
            apply_url=f"https://{src['slug']}.bamboohr.com/careers/{j.get('id')}",
            source_kind="bamboohr", source_slug=src["slug"],
        ))
    return out


def from_personio(src):
    import xml.etree.ElementTree as ET
    r = requests.get(f"https://{src['slug']}.jobs.personio.com/xml",
                     headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out = []
    for p in root.findall(".//position"):
        g = lambda t: (p.findtext(t) or "").strip()  # noqa: E731
        out.append(make_job(
            title=g("name"),
            company_name=src["company_name"],
            location=g("office"),
            employment_type=g("employmentType").lower() or None,
            summary=clean_text(g("jobDescriptions")),
            apply_url=f"https://{src['slug']}.jobs.personio.com/job/{g('id')}",
            posted_at=iso(g("createdAt")),
            source_kind="personio", source_slug=src["slug"],
        ))
    return out


def _generic_board(src, url, mapping, root_key):
    """لوحات عامة مفتوحة (وظائف عن بُعد) — متاحة مجاناً بدون مفتاح."""
    data = get_json(url)
    items = data.get(root_key, data if isinstance(data, list) else [])
    out = []
    for j in items:
        loc = j.get(mapping["location"]) or ""
        out.append(make_job(
            title=j.get(mapping["title"]),
            company_name=j.get(mapping["company"]) or src["company_name"],
            location=loc,
            summary=clean_text(j.get(mapping["summary"])),
            apply_url=j.get(mapping["url"]),
            posted_at=iso(j.get(mapping["date"])),
            is_remote=True,
            source_kind=src["kind"], source_slug=src.get("slug", src["kind"]),
        ))
    return out


def from_arbeitnow(src):
    return _generic_board(src, "https://www.arbeitnow.com/api/job-board-api", {
        "title": "title", "company": "company_name", "location": "location",
        "summary": "description", "url": "url", "date": "created_at"}, "data")


def from_remotive(src):
    return _generic_board(src, "https://remotive.com/api/remote-jobs", {
        "title": "title", "company": "company_name", "location": "candidate_required_location",
        "summary": "description", "url": "url", "date": "publication_date"}, "jobs")


def from_jobicy(src):
    return _generic_board(src, "https://jobicy.com/api/v2/remote-jobs?count=50", {
        "title": "jobTitle", "company": "companyName", "location": "jobGeo",
        "summary": "jobExcerpt", "url": "url", "date": "pubDate"}, "jobs")


def from_himalayas(src):
    data = get_json("https://himalayas.app/jobs/api", {"limit": 100})
    out = []
    for j in data.get("jobs", data if isinstance(data, list) else []):
        loc = j.get("locationRestrictions") or j.get("location") or ""
        if isinstance(loc, list):
            loc = ", ".join(str(x) for x in loc)
        out.append(make_job(
            title=j.get("title"),
            company_name=j.get("companyName") or j.get("company") or "غير محدد",
            location=loc or "Worldwide",
            summary=clean_text(j.get("excerpt") or j.get("description")),
            apply_url=j.get("applicationLink") or j.get("guid") or j.get("url"),
            posted_at=iso(j.get("pubDate") or j.get("publishedAt")),
            is_remote=True,
            source_kind="himalayas", source_slug="himalayas",
        ))
    return out


def from_remoteok(src):
    """RemoteOK يشترط ذكر المصدر ووضع رابط للوظيفة الأصلية — وده اللي بنعمله."""
    data = get_json("https://remoteok.com/api")
    out = []
    for j in data:
        if not j.get("position"):        # أول عنصر إشعار قانوني
            continue
        out.append(make_job(
            title=j.get("position"),
            company_name=j.get("company") or "غير محدد",
            location=j.get("location") or "Worldwide",
            summary=clean_text(j.get("description")),
            apply_url=j.get("url") or j.get("apply_url"),
            posted_at=iso(j.get("date")),
            is_remote=True,
            source_kind="remoteok", source_slug="remoteok",
        ))
    return out


def from_weworkremotely(src):
    import xml.etree.ElementTree as ET
    r = requests.get("https://weworkremotely.com/remote-jobs.rss",
                     headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out = []
    for item in root.findall(".//item"):
        g = lambda t: (item.findtext(t) or "").strip()   # noqa: E731
        raw = g("title")                                  # "Company: Job Title"
        company, _, title = raw.partition(":")
        out.append(make_job(
            title=(title or raw).strip(),
            company_name=(company or "غير محدد").strip(),
            location=g("region") or "Worldwide",
            summary=clean_text(g("description")),
            apply_url=g("link"),
            posted_at=iso_rfc(g("pubDate")),
            is_remote=True,
            source_kind="weworkremotely", source_slug="wwr",
        ))
    return out


def from_jooble(src):
    """Jooble — مفتاح مجاني من jooble.org/api/about (تغطية كويت ومصر قوية)."""
    key = os.getenv("JOOBLE_KEY")
    if not key:
        raise RuntimeError("محتاج JOOBLE_KEY")
    body = {"keywords": src.get("keywords", ""), "location": src.get("location", ""),
            "page": str(src.get("page", 1))}
    # الـ API على jooble.org فقط — النطاقات الفرعية للموقع مش للواجهة
    r = requests.post(f"https://jooble.org/api/{key}",
                      json=body, headers={"Content-Type": "application/json", "User-Agent": UA},
                      timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for j in r.json().get("jobs", []):
        out.append(make_job(
            title=j.get("title"),
            company_name=j.get("company") or "غير محدد",
            location=j.get("location"),
            employment_type=(j.get("type") or "").lower().replace(" ", "_") or None,
            summary=clean_text(j.get("snippet")),
            apply_url=j.get("link"),
            posted_at=iso(j.get("updated")),
            country=src.get("country"),
            source_kind="jooble", source_slug=src.get("slug", "jooble"),
        ))
    return out


FETCHERS = {
    "greenhouse": from_greenhouse,
    "lever": from_lever,
    "workable": from_workable,
    "smartrecruiters": from_smartrecruiters,
    "recruitee": from_recruitee,
    "careerjet": from_careerjet,
    "ashby": from_ashby,
    "bamboohr": from_bamboohr,
    "personio": from_personio,
    "arbeitnow": from_arbeitnow,
    "remotive": from_remotive,
    "jobicy": from_jobicy,
    "himalayas": from_himalayas,
    "remoteok": from_remoteok,
    "weworkremotely": from_weworkremotely,
    "jooble": from_jooble,
}


# ------------------------------------------------------------------
# الرفع على Supabase (اختياري)
# ------------------------------------------------------------------
def push_to_supabase(jobs):
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not (url and key):
        return "تخطّي الرفع — متغيرات Supabase غير مضبوطة"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    payload = []
    now = datetime.now(timezone.utc).isoformat()
    for j in jobs:
        payload.append({
            "fingerprint": j["fingerprint"], "title": j["title"],
            "company_name": j["company_name"], "city": j["city"], "country": j["country"],
            "category": j["category"], "seniority": j["seniority"],
            "employment_type": j["employment_type"], "is_remote": j["is_remote"],
            "summary": j["summary"], "apply_url": j["apply_url"],
            "source_kind": j["source_kind"], "posted_at": j["posted_at"],
            "last_seen_at": now, "is_open": True,
        })
    sent = 0
    for i in range(0, len(payload), 500):
        chunk = payload[i:i + 500]
        r = requests.post(f"{url}/rest/v1/jobs?on_conflict=fingerprint",
                          headers=headers, data=json.dumps(chunk), timeout=60)
        r.raise_for_status()
        sent += len(chunk)
    return f"تم رفع {sent} شاغر"


# ------------------------------------------------------------------
# التشغيل
# ------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="sources.json")
    ap.add_argument("--out", default="../web/data")
    ap.add_argument("--all-countries", action="store_true", help="بدون فلتر الخليج ومصر")
    ap.add_argument("--push", action="store_true", help="ارفع على Supabase")
    args = ap.parse_args()

    sources = json.loads(Path(args.sources).read_text(encoding="utf-8"))
    sources = [s for s in sources if "kind" in s and s.get("is_active", True)]

    raw, report = [], {"started_at": datetime.now(timezone.utc).isoformat(), "sources": []}

    for src in sources:
        fetcher = FETCHERS.get(src["kind"])
        entry = {"kind": src["kind"], "slug": src.get("slug"), "count": 0, "status": "ok"}
        if not fetcher:
            entry["status"] = "نوع مصدر غير معروف"
        else:
            try:
                jobs = fetcher(src)
                raw.extend(jobs)
                entry["count"] = len(jobs)
            except Exception as exc:                      # noqa: BLE001
                entry["status"] = f"{type(exc).__name__}: {exc}"[:160]
            time.sleep(SLEEP_BETWEEN)
        report["sources"].append(entry)
        print(f"[{entry['status']:>12}] {src['kind']:<16} {src.get('slug',''):<24} {entry['count']:>4}", file=sys.stderr)

    # فلتر جغرافي — مع الإبقاء على الوظائف عن بُعد المفتوحة للمنطقة
    REMOTE_OK = ("worldwide", "anywhere", "global", "emea", "mena", "middle east",
                 "remote", "عن بعد", "عن بُعد")
    if args.all_countries:
        geo = raw
    else:
        geo = []
        for j in raw:
            if j["country"] in COUNTRY_PATTERNS:
                geo.append(j)
            elif j["is_remote"] and any(k in (j["location_raw"] or "").lower() for k in REMOTE_OK):
                j["country"] = "RM"          # عن بُعد — مفتوحة للمنطقة
                j["city"] = None
                geo.append(j)

    # إزالة المكرر — الأحدث يكسب
    seen = {}
    for j in sorted(geo, key=lambda x: x["posted_at"] or "", reverse=True):
        if not j["title"] or not j["apply_url"]:
            continue
        seen.setdefault(j["fingerprint"], j)
    jobs = list(seen.values())
    jobs.sort(key=lambda x: x["posted_at"] or "", reverse=True)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(jobs),
        "jobs": jobs,
    }
    (out_dir / "jobs.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    report.update({
        "raw": len(raw), "after_geo": len(geo), "after_dedupe": len(jobs),
        "finished_at": datetime.now(timezone.utc).isoformat(),
    })
    if args.push:
        report["push"] = push_to_supabase(jobs)
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nالخام {len(raw)} → بعد الفلتر الجغرافي {len(geo)} → بعد إزالة المكرر {len(jobs)}", file=sys.stderr)
    print(f"الملف: {out_dir/'jobs.json'}", file=sys.stderr)


if __name__ == "__main__":
    main()
