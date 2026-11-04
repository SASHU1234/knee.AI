-- Knee.AI: append-only clinician review log.  ADDITIVE migration - touches no existing table.
-- Apply in the Supabase SQL editor (or psql). Rollback: see the end of this file.

create table if not exists public.study_reviews (
  review_id        text primary key,
  study_id         text        not null,          -- analyses.analysis_id (the text key the app uses)
  finding_id       text        not null,
  finding_kind     text,
  finding_title    text,
  content_sha256   text,                          -- hash of the reviewed AI text, if any
  content_snapshot text,                          -- exact AI text that was reviewed (<= 12000 chars)
  reviewer_id      uuid        not null default auth.uid() references auth.users (id),
  decision         text        not null check (decision in ('confirmed','needs_further_review','disagreed')),
  comment          text        not null default '' check (char_length(comment) <= 1000),
  previous_state   text        not null,
  new_state        text        not null,
  sequence         integer     not null check (sequence >= 1),
  request_id       text,
  created_at       timestamptz not null default now()
);

-- Concurrency + idempotency: one writer wins a given sequence; a request id is applied once.
create unique index if not exists study_reviews_seq_uq
  on public.study_reviews (study_id, finding_id, reviewer_id, sequence);
create unique index if not exists study_reviews_req_uq
  on public.study_reviews (study_id, reviewer_id, request_id) where request_id is not null;
create index if not exists study_reviews_study_idx on public.study_reviews (study_id, created_at);

alter table public.study_reviews enable row level security;

-- Reviewers may read their own events and insert events for studies they own.
-- There is deliberately NO update or delete policy: the log is append-only.
create policy "study_reviews_select_own" on public.study_reviews
  for select using (reviewer_id = auth.uid());

create policy "study_reviews_insert_own" on public.study_reviews
  for insert with check (
    reviewer_id = auth.uid()
    and exists (select 1 from public.analyses a
                where a.analysis_id = study_reviews.study_id and a.user_id = auth.uid())
  );

-- ROLLBACK (permanently removes the review history):
--   drop table if exists public.study_reviews;
