create extension if not exists pgcrypto;

create table if not exists public.leads (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    name text not null,
    email text not null,
    phone text not null,
    company text not null,
    doors integer not null check (doors >= 0),
    message text not null,
    fit_score integer not null check (fit_score between 1 and 5),
    reason text not null,
    intent text not null check (intent in ('low', 'medium', 'high')),
    suggested_reply text not null,
    processing_ms integer,
    source text not null default 'facebook_lead_ad_simulation'
);

-- The backend uses the Supabase service-role key, stored only in server environment
-- variables. Never expose that key in browser/client-side code.
