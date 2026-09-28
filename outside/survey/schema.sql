-- The survey page outside the clinic: what it holds, and nothing more.
--
-- Run once in the Supabase project's SQL editor (see README.md).
--
-- Only three things ever leave the clinic: the clinic's name and logo
-- (brand), and per survey a random code with the unit's name and the
-- questions (surveys). No child's name, no phone number, no diagnosis.
-- The family's answers wait here (answers) until the clinic's program
-- collects them, and are deleted — with their survey — once it has.
--
-- Row-level security is switched on with no policies: nobody reaches these
-- tables with the public key. Only the page's own functions on Vercel do,
-- with the service key kept in Vercel's settings and nowhere else.

create table if not exists brand (
  id          int primary key default 1 check (id = 1),
  config      jsonb not null,
  updated_at  timestamptz not null default now()
);

create table if not exists surveys (
  token       text primary key,
  config      jsonb not null,
  created_at  timestamptz not null default now(),
  expires_at  timestamptz not null
);

create table if not exists answers (
  token        text primary key references surveys (token) on delete cascade,
  payload      jsonb not null,
  submitted_at timestamptz not null default now()
);

alter table brand   enable row level security;
alter table surveys enable row level security;
alter table answers enable row level security;
