-- ============================================================
-- شواغر — إضافات النسخة الثانية
-- النشر من المستخدمين + الدخول بجوجل + الإعلانات
-- شغّله بعد schema.sql في Supabase > SQL Editor
-- ============================================================

-- ------------------------------------------------------------
-- ١) الوظائف المنشورة من المستخدمين (تحت المراجعة)
-- ------------------------------------------------------------
create table if not exists job_submissions (
  id            bigserial primary key,
  submitter_id  uuid references auth.users(id) on delete set null,
  submitter_name  text,
  submitter_email text,
  title         text not null,
  company_name  text not null,
  country       text,
  city          text,
  category      text,
  seniority     text,
  employment_type text default 'full_time',
  is_remote     boolean default false,
  salary_note   text,
  summary       text,
  apply_url     text not null,
  status        text not null default 'pending',   -- pending | approved | rejected
  reject_reason text,
  is_featured   boolean not null default false,
  featured_until timestamptz,
  created_at    timestamptz not null default now(),
  reviewed_at   timestamptz
);

create index if not exists subs_status_idx on job_submissions (status, created_at desc);

alter table job_submissions enable row level security;

-- أي حد (حتى الضيف) يقدر ينشر
create policy "anyone can submit" on job_submissions
  for insert with check (true);

-- الكل يشوف المعتمد فقط
create policy "read approved" on job_submissions
  for select using (status = 'approved');

-- صاحب الإعلان يشوف إعلاناته ويعدّلها وهي تحت المراجعة
create policy "own submissions" on job_submissions
  for select using (auth.uid() = submitter_id);
create policy "edit own pending" on job_submissions
  for update using (auth.uid() = submitter_id and status = 'pending')
  with check (auth.uid() = submitter_id);

-- ------------------------------------------------------------
-- ٢) الإعلانات المدفوعة
-- ------------------------------------------------------------
create table if not exists ads (
  id          bigserial primary key,
  advertiser  text not null,
  title       text not null,
  body        text,
  image_url   text,
  target_url  text not null,
  placement   text not null default 'inline',   -- hero | inline | rail
  country     text,                              -- استهداف دولة (فارغ = الكل)
  category    text,                              -- استهداف مجال
  starts_at   timestamptz not null default now(),
  ends_at     timestamptz,
  price_kwd   numeric(8,2),
  is_active   boolean not null default true,
  impressions bigint not null default 0,
  clicks      bigint not null default 0,
  created_at  timestamptz not null default now()
);

create index if not exists ads_live_idx on ads (is_active, placement, ends_at);

alter table ads enable row level security;
create policy "ads are public" on ads for select
  using (is_active and (ends_at is null or ends_at > now()));

-- عدّاد النقرات (يستدعى من الموقع)
create or replace function ad_click(ad bigint)
returns void as $$
  update ads set clicks = clicks + 1 where id = ad;
$$ language sql security definer;

-- ------------------------------------------------------------
-- ٣) جروبات وقنوات واتساب
-- ------------------------------------------------------------
create table if not exists wa_groups (
  id          bigserial primary key,
  name        text not null,
  kind        text not null default 'jobs',    -- jobs | courses
  type        text not null default 'group',   -- group | channel
  country     text,
  category    text,
  url         text not null,
  note        text,
  submitted_by uuid references auth.users(id) on delete set null,
  status      text not null default 'pending', -- pending | approved
  created_at  timestamptz not null default now()
);

alter table wa_groups enable row level security;
create policy "approved groups public" on wa_groups for select using (status = 'approved');
create policy "anyone can suggest group" on wa_groups for insert with check (true);

-- ------------------------------------------------------------
-- ٤) عرض موحّد للموقع: المصادر + المعتمد من المستخدمين
-- ------------------------------------------------------------
create or replace view v_live_jobs as
  select title, company_name, country, city, category, seniority,
         employment_type, is_remote, summary, apply_url,
         source_kind, posted_at, is_featured, false as user_posted
    from jobs where is_open
  union all
  select title, company_name, country, city, category, seniority,
         employment_type, is_remote, summary, apply_url,
         'user'::text, created_at, is_featured, true
    from job_submissions where status = 'approved';
