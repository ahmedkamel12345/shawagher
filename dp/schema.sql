-- ============================================================
-- شواغر | Shawagher — قاعدة البيانات (PostgreSQL / Supabase)
-- شغّل الملف ده كامل في Supabase > SQL Editor
-- ============================================================

create extension if not exists pg_trgm;
create extension if not exists "uuid-ossp";

-- ------------------------------------------------------------
-- 1) المصادر: كل بورد أو API بنسحب منه
-- ------------------------------------------------------------
create table if not exists sources (
  id            bigserial primary key,
  kind          text not null,              -- greenhouse | lever | workable | smartrecruiters | recruitee | careerjet | manual
  slug          text not null,              -- board token / company handle
  company_name  text not null,
  site_url      text,
  country_hint  text,                       -- KW | SA | AE | QA | BH | OM | EG
  is_active     boolean not null default true,
  last_fetch_at timestamptz,
  last_status   text,
  fetched_count integer default 0,
  created_at    timestamptz not null default now(),
  unique (kind, slug)
);

-- ------------------------------------------------------------
-- 2) الشركات
-- ------------------------------------------------------------
create table if not exists companies (
  id          bigserial primary key,
  name        text not null,
  name_ar     text,
  slug        text not null unique,
  logo_url    text,
  website     text,
  is_verified boolean not null default false,   -- شركة سجّلت عندنا ودفعت
  created_at  timestamptz not null default now()
);

-- ------------------------------------------------------------
-- 3) الشواغر — الجدول الرئيسي
-- fingerprint = sha1(company|title|city) لمنع التكرار بين المصادر
-- ------------------------------------------------------------
create table if not exists jobs (
  id             bigserial primary key,
  fingerprint    text not null unique,
  title          text not null,
  title_ar       text,
  company_id     bigint references companies(id) on delete set null,
  company_name   text not null,
  city           text,
  country        text,                       -- KW | SA | AE | QA | BH | OM | EG
  category       text,                       -- accounting | sales | it | hr | ops | health | education | other
  seniority      text,                       -- entry | mid | senior | manager
  employment_type text,                      -- full_time | part_time | contract | internship
  is_remote      boolean default false,
  summary        text,                       -- ملخص قصير فقط — ممنوع نسخ الإعلان كامل
  summary_ar     text,
  apply_url      text not null,              -- التقديم يتم على المصدر الأصلي
  source_kind    text not null,
  source_id      bigint references sources(id) on delete set null,
  posted_at      timestamptz,
  first_seen_at  timestamptz not null default now(),
  last_seen_at   timestamptz not null default now(),
  is_open        boolean not null default true,
  -- إعلانات مدفوعة من أصحاب العمل مباشرة
  is_direct      boolean not null default false,
  is_featured    boolean not null default false,
  featured_until timestamptz,
  -- متطلبات المنصة
  requires_test  boolean not null default false,
  test_id        bigint,
  requires_video boolean not null default false,
  search_tsv     tsvector
);

create index if not exists jobs_open_idx      on jobs (is_open, posted_at desc nulls last);
create index if not exists jobs_country_idx   on jobs (country, category);
create index if not exists jobs_featured_idx  on jobs (is_featured, featured_until);
create index if not exists jobs_title_trgm    on jobs using gin (title gin_trgm_ops);
create index if not exists jobs_tsv_idx       on jobs using gin (search_tsv);

create or replace function jobs_tsv_update() returns trigger as $$
begin
  new.search_tsv :=
      setweight(to_tsvector('simple', coalesce(new.title,'') || ' ' || coalesce(new.title_ar,'')), 'A')
   || setweight(to_tsvector('simple', coalesce(new.company_name,'')), 'B')
   || setweight(to_tsvector('simple', coalesce(new.city,'') || ' ' || coalesce(new.summary_ar,'')), 'C');
  return new;
end $$ language plpgsql;

drop trigger if exists jobs_tsv_trg on jobs;
create trigger jobs_tsv_trg before insert or update on jobs
for each row execute function jobs_tsv_update();

-- ------------------------------------------------------------
-- 4) الباحثون عن العمل
-- ------------------------------------------------------------
create table if not exists profiles (
  id              uuid primary key,          -- = auth.users.id
  full_name       text,
  phone           text,
  country         text,
  city            text,
  headline        text,
  years_experience smallint,
  categories      text[],                    -- المجالات المهتم بيها
  cv_url          text,
  video_ar_url    text,                      -- الفيديو التعريفي بالعربي
  video_en_url    text,                      -- الفيديو التعريفي بالإنجليزي
  video_ar_transcript text,
  video_en_transcript text,
  is_searchable   boolean not null default true,
  created_at      timestamptz not null default now()
);

create table if not exists saved_jobs (
  profile_id uuid references profiles(id) on delete cascade,
  job_id     bigint references jobs(id) on delete cascade,
  saved_at   timestamptz not null default now(),
  primary key (profile_id, job_id)
);

create table if not exists job_alerts (
  id          bigserial primary key,
  profile_id  uuid references profiles(id) on delete cascade,
  keywords    text,
  countries   text[],
  categories  text[],
  frequency   text not null default 'daily',   -- daily | weekly
  last_sent_at timestamptz,
  is_active   boolean not null default true
);

-- ------------------------------------------------------------
-- 5) الاختبارات
-- ------------------------------------------------------------
create table if not exists tests (
  id          bigserial primary key,
  slug        text not null unique,
  title_ar    text not null,
  title_en    text,
  category    text not null,
  duration_min smallint not null default 15,
  pass_score  smallint not null default 60,
  is_active   boolean not null default true
);

create table if not exists test_questions (
  id          bigserial primary key,
  test_id     bigint not null references tests(id) on delete cascade,
  prompt_ar   text not null,
  prompt_en   text,
  choices     jsonb not null,      -- [{"id":"a","ar":"...","en":"..."}]
  correct_id  text not null,
  weight      smallint not null default 1
);

create table if not exists test_attempts (
  id          bigserial primary key,
  profile_id  uuid references profiles(id) on delete cascade,
  test_id     bigint references tests(id) on delete cascade,
  score       smallint,
  passed      boolean,
  answers     jsonb,
  started_at  timestamptz not null default now(),
  finished_at timestamptz,
  expires_at  timestamptz            -- الشارة صالحة ٦ شهور
);

create index if not exists attempts_profile_idx on test_attempts (profile_id, test_id, passed);

-- ------------------------------------------------------------
-- 6) الشركات المشتركة والتقديمات
-- ------------------------------------------------------------
create table if not exists employers (
  id           bigserial primary key,
  owner_id     uuid references profiles(id) on delete set null,
  company_id   bigint references companies(id) on delete cascade,
  plan         text not null default 'free',   -- free | starter | pro
  plan_expires timestamptz,
  job_credits  smallint not null default 0,
  cv_access    boolean not null default false,
  created_at   timestamptz not null default now()
);

create table if not exists applications (
  id           bigserial primary key,
  job_id       bigint references jobs(id) on delete cascade,
  profile_id   uuid references profiles(id) on delete cascade,
  status       text not null default 'new',   -- new | shortlisted | rejected | hired
  test_score   smallint,
  employer_note text,
  created_at   timestamptz not null default now(),
  unique (job_id, profile_id)
);

-- ------------------------------------------------------------
-- 7) صلاحيات الوصول (RLS)
-- الشواغر مقروءة للجميع؛ البيانات الشخصية لصاحبها فقط
-- ------------------------------------------------------------
alter table jobs      enable row level security;
alter table profiles  enable row level security;
alter table saved_jobs enable row level security;
alter table test_attempts enable row level security;

create policy "jobs are public" on jobs for select using (true);

create policy "own profile" on profiles
  for all using (auth.uid() = id) with check (auth.uid() = id);

create policy "own saved jobs" on saved_jobs
  for all using (auth.uid() = profile_id) with check (auth.uid() = profile_id);

create policy "own attempts" on test_attempts
  for all using (auth.uid() = profile_id) with check (auth.uid() = profile_id);

-- ------------------------------------------------------------
-- 8) إغلاق الشواغر اللي اختفت من المصدر
-- شغّلها بعد كل دورة تجميع
-- ------------------------------------------------------------
create or replace function close_stale_jobs(stale_days int default 14)
returns integer as $$
declare n integer;
begin
  update jobs set is_open = false
   where is_open = true
     and is_direct = false
     and last_seen_at < now() - (stale_days || ' days')::interval;
  get diagnostics n = row_count;
  return n;
end $$ language plpgsql;
