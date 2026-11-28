-- Section 04C — dedicated historical reconciliation evidence (schema only).
-- NO INSERTS / NO FINANCIAL POSTING / NO PUBLIC OR ANON GRANTS.
-- Existing gs_streamlit_v1 financial tables are not altered.

create table if not exists gs_streamlit_v1.reconciliation_evidence_sources (
  id bigint generated always as identity primary key,
  source_kind text not null check (source_kind in (
    'current_individual_review','individual_review_audit',
    'current_receipt_split','cheque_clearance','cheque_allocation',
    'legacy_reference_ignored','legacy_reference_reassignment',
    'archived_individual_review','historical_bank_statement'
  )),
  source_filename text not null check (length(btrim(source_filename)) > 0),
  sha256 text not null check (sha256 ~ '^[a-f0-9]{64}$'),
  record_count integer not null check (record_count >= 0),
  import_state text not null default 'proposed'
    check (import_state in ('proposed','staged','verified','rejected')),
  note text,
  recorded_at timestamptz not null default now(),
  unique(source_kind, sha256)
);

create table if not exists gs_streamlit_v1.reconciliation_decision_events (
  id bigint generated always as identity primary key,
  source_id bigint not null references gs_streamlit_v1.reconciliation_evidence_sources(id) on delete restrict,
  source_record_key text not null check(length(btrim(source_record_key)) > 0),
  source_event_index integer not null check(source_event_index >= 0),
  historical_bank_row_id text,
  bank_reference text,
  decision_class text not null check (decision_class in (
    'assign','exclude','pending','restore','split_receipt',
    'cheque_clearance','cheque_rent_allocation','legacy_hint','correction'
  )),
  tenancy_id_as_reviewed text,
  decision_payload jsonb not null default '{}'::jsonb
    check(jsonb_typeof(decision_payload) in ('object','array')),
  reviewer text,
  reviewed_at timestamptz,
  reason text,
  supersedes_event_id bigint references gs_streamlit_v1.reconciliation_decision_events(id) on delete restrict,
  identity_resolution_state text not null default 'unmatched'
    check(identity_resolution_state in ('exact_row','candidate_only','unmatched')),
  posting_state text not null default 'evidence_only'
    check(posting_state in ('not_applicable','evidence_only','approved_ledger_pending','posted_verified')),
  recorded_at timestamptz not null default now(),
  unique (source_id, source_record_key, source_event_index),
  check (supersedes_event_id is null or supersedes_event_id <> id)
);

create table if not exists gs_streamlit_v1.reconciliation_movement_links (
  id bigint generated always as identity primary key,
  decision_event_id bigint not null references gs_streamlit_v1.reconciliation_decision_events(id) on delete restrict,
  movement_id bigint references gs_streamlit_v1.bank_movements(id) on delete restrict,
  bank_statement_row_id text,
  match_state text not null default 'proposed' check(match_state in ('proposed','verified','rejected')),
  evidence_note text,
  reviewed_by text,
  reviewed_at timestamptz,
  created_at timestamptz not null default now(),
  check (match_state <> 'verified' or
    (movement_id is not null and length(btrim(coalesce(evidence_note,''))) >= 15
     and length(btrim(coalesce(reviewed_by,''))) > 0 and reviewed_at is not null))
);

create index if not exists reconciliation_decision_events_bank_row_idx
  on gs_streamlit_v1.reconciliation_decision_events(historical_bank_row_id);
create index if not exists reconciliation_decision_events_reference_idx
  on gs_streamlit_v1.reconciliation_decision_events(bank_reference);
create index if not exists reconciliation_links_decision_idx
  on gs_streamlit_v1.reconciliation_movement_links(decision_event_id);
create index if not exists reconciliation_links_movement_idx
  on gs_streamlit_v1.reconciliation_movement_links(movement_id);
create unique index if not exists reconciliation_links_unique_verified_event_movement
  on gs_streamlit_v1.reconciliation_movement_links(decision_event_id, movement_id)
  where movement_id is not null and match_state = 'verified';

alter table gs_streamlit_v1.reconciliation_evidence_sources enable row level security;
alter table gs_streamlit_v1.reconciliation_decision_events enable row level security;
alter table gs_streamlit_v1.reconciliation_movement_links enable row level security;

revoke all on table gs_streamlit_v1.reconciliation_evidence_sources from public, anon, authenticated;
revoke all on table gs_streamlit_v1.reconciliation_decision_events from public, anon, authenticated;
revoke all on table gs_streamlit_v1.reconciliation_movement_links from public, anon, authenticated;
revoke all on sequence gs_streamlit_v1.reconciliation_evidence_sources_id_seq from public, anon, authenticated;
revoke all on sequence gs_streamlit_v1.reconciliation_decision_events_id_seq from public, anon, authenticated;
revoke all on sequence gs_streamlit_v1.reconciliation_movement_links_id_seq from public, anon, authenticated;

-- No permissive RLS policies or writer grants are created.
-- The existing GS_V1_READONLY_DSN is not changed.
