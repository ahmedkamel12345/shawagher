# شواغر | Shawagher

لوحة وظائف يومية للخليج ومصر. تجمع الشواغر من صفحات التوظيف الرسمية، توحّدها،
تشيل المكرر، وتعرضها بالعربي — والتقديم يتم على موقع الجهة مباشرة.

من إعداد وتطوير المحترف للاستشارات المالية — أحمد أبو كامل.

```
shawagher/
├── .github/workflows/collect.yml   التشغيل التلقائي كل ٦ ساعات
├── collector/
│   ├── fetch_jobs.py               المجمّع الرئيسي (١٦ نوع مصدر)
│   ├── check_sources.py            فحص المصادر (--prune يعطّل الفاشل)
│   ├── merge_manual.py             ضم إعلانات واتساب لملف الوظائف
│   ├── enable_careerjet.py         تفعيل/تعطيل مصادر Careerjet
│   ├── enable_jooble.py            تفعيل/تعطيل مصادر Jooble
│   └── sources.json                قائمة المصادر (١٧٠ مصدر)
├── db/schema.sql                   قاعدة البيانات (Supabase)
└── web/
    ├── index.html                  الموقع (داشبورد + دليل واتساب)
    ├── whatsapp-import.html        أداة تحويل إعلانات واتساب لوظائف
    ├── assets/                     اللوجوهات
    └── data/                       jobs.json · groups.json · manual.json
```

## التشغيل المحلي

```bash
cd collector
pip install requests
python check_sources.py sources.json --prune     # فحص المصادر
python fetch_jobs.py --sources sources.json --out ../web/data
python merge_manual.py --manual ../web/data/manual.json --jobs ../web/data/jobs.json
cd ../web && python -m http.server 8000          # ثم افتح localhost:8000
```

## المفاتيح (اختيارية)

```bash
set CAREERJET_API_KEY=...     # careerjet.com/partners/api
set JOOBLE_KEY=...            # jooble.org/api/about
python enable_careerjet.py
python enable_jooble.py
```

بدون مفاتيح المجمّع بيشتغل عادي على ٣٠+ مصدر مفتوح.

## التشغيل التلقائي

ارفع المشروع على GitHub، حط المفتاحين في Settings ← Secrets ← Actions،
واربط Netlify بالمستودع مع **Publish directory: `web`**.
بعدها التحديث بيتم لوحده كل ٦ ساعات. التفاصيل في `التحديث-من-الموبايل.md`.

## قواعد ثابتة

- **متعملش scraping** للينكدإن أو إنديد أو بيت ولا تقرا جروبات واتساب ببرامج غير رسمية —
  مخالف لشروط الاستخدام وممكن يوقف المشروع كله.
- **متنسخش نص الإعلان كامل** — ملخص ≤ ٢٨٠ حرف + رابط المصدر.
- **مفيش رسوم على الباحث عن العمل** — ممنوع قانوناً في الكويت ودول الخليج. الدخل من أصحاب العمل.
- ضيف `JobPosting` Schema.org على صفحات الوظائف → دخول Google for Jobs.
