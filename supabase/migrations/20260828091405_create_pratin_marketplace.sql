create schema if not exists pratin;

revoke all on schema pratin from public, anon, authenticated;
grant usage on schema pratin to postgres, service_role;

create table if not exists pratin.opportunities (
  id text primary key,
  created_at timestamptz not null,
  status text not null check (status in ('CREATED', 'MARKET_RUN', 'SETTLED')),
  payload jsonb not null
);

create table if not exists pratin.providers (
  id text primary key,
  payload jsonb not null
);

create table if not exists pratin.settlements (
  id text primary key,
  opportunity_id text not null unique references pratin.opportunities(id) on delete restrict,
  offer_id text not null,
  provider_id text not null references pratin.providers(id) on delete restrict,
  settled_at timestamptz not null,
  payload jsonb not null
);

create table if not exists pratin.audit_events (
  id text primary key,
  timestamp timestamptz not null,
  event_type text not null,
  opportunity_id text,
  payload jsonb not null
);

create table if not exists pratin.invoices (
  id text primary key,
  invoice_number text,
  status text not null check (status in ('PARSED', 'PARTIAL', 'SETTLED')),
  created_at timestamptz not null,
  updated_at timestamptz not null,
  payload jsonb not null
);

create index if not exists invoices_invoice_number_idx
  on pratin.invoices (invoice_number);
create index if not exists invoices_created_at_idx
  on pratin.invoices (created_at desc);

create index if not exists opportunities_status_created_idx
  on pratin.opportunities (status, created_at desc);
create index if not exists settlements_provider_settled_idx
  on pratin.settlements (provider_id, settled_at desc);
create index if not exists audit_events_opportunity_timestamp_idx
  on pratin.audit_events (opportunity_id, timestamp desc);
create index if not exists audit_events_timestamp_idx
  on pratin.audit_events (timestamp desc);

alter table pratin.opportunities enable row level security;
alter table pratin.providers enable row level security;
alter table pratin.settlements enable row level security;
alter table pratin.audit_events enable row level security;
alter table pratin.invoices enable row level security;

revoke all on all tables in schema pratin from public, anon, authenticated;
grant select, insert, update, delete on all tables in schema pratin to service_role;

alter default privileges in schema pratin revoke all on tables from public, anon, authenticated;
alter default privileges in schema pratin grant select, insert, update, delete on tables to service_role;

comment on schema pratin is 'Private backend-owned state for the synthetic PRATIN marketplace.';
comment on table pratin.settlements is 'Simulated settlements only; no real funds move.';
