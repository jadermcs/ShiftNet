-- Demo contributions, for trying the contributor and moderator views locally.
-- Run after the migrations and supabase/seed.sql, with a privileged connection.
--
-- The two demo accounts use the reserved .invalid domain and have no sign-in identity: they only
-- own the demo rows. To review, sign in once with your own address, then make yourself a moderator:
--
--   insert into public.moderators (user_id, note)
--   select id, 'local moderator' from auth.users where email = 'you@example.org';

insert into auth.users (
  instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
  raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
  confirmation_token, recovery_token, email_change_token_new, email_change
) values
  ('00000000-0000-0000-0000-000000000000', 'd0000000-0000-4000-8000-000000000001', 'authenticated', 'authenticated',
   'contributor@shiftnet.invalid', '', now(), '{"provider": "email", "providers": ["email"]}', '{}', now(), now(), '', '', '', ''),
  ('00000000-0000-0000-0000-000000000000', 'd0000000-0000-4000-8000-000000000002', 'authenticated', 'authenticated',
   'moderator@shiftnet.invalid', '', now(), '{"provider": "email", "providers": ["email"]}', '{}', now(), now(), '', '', '', '')
on conflict (id) do nothing;

insert into public.moderators (user_id, note)
values ('d0000000-0000-4000-8000-000000000002', 'demo moderator')
on conflict (user_id) do nothing;

-- Submit as the demo contributor, so the rows go through the same automatic checks as the site's.
select set_config('request.jwt.claims', '{"sub": "d0000000-0000-4000-8000-000000000001", "role": "authenticated"}', false);

-- Passes every check: published at once as auto-checked.
select status, validation from public.submit_usage('{
  "sense_id": "cloud.n.06",
  "quote": "Most small firms will keep their accounts in the cloud within a few years, the report predicts.",
  "year": 2009,
  "source": {"kind": "newspaper", "title": "Small business goes online", "publisher": "The Example Times",
             "published_year": 2009, "url": "https://news.example.org/2009/small-business-cloud", "accessed_on": "2026-10-01"}
}'::jsonb);

-- Earlier than the recorded date (an antedating): waits for a moderator.
select status, validation from public.submit_usage('{
  "sense_id": "troll.v.02",
  "quote": "He was only trolling the group to see who would take the bait.",
  "year": 1988,
  "locator": "message 14",
  "source": {"kind": "archive", "title": "Usenet newsgroup archive", "identifier": "alt.folklore.urban/1988-04"}
}'::jsonb);

-- The quote does not use the word and the reference cannot be checked: waits, then rejected below.
select status, validation from public.submit_usage('{
  "sense_id": "mouse.n.04",
  "quote": "She moved the little box across the desk to steer the pointer on the screen.",
  "year": 1972,
  "source": {"kind": "other", "title": "Lab notebook"}
}'::jsonb);

-- A new sense with a supporting usage; a first-time contributor, so it waits for a moderator.
select status, validation from public.submit_sense('{
  "lemma": "viral",
  "pos": "adjective",
  "gloss": "relating to marketing that spreads by people passing it on to each other",
  "examples": ["a viral campaign"],
  "date_label": "late 1990s",
  "date_earliest": 1997,
  "shift": "narrowing",
  "date_source": "Marketing trade press",
  "source_type": "corpus",
  "parents": ["viral.adj.02"],
  "usage": {
    "quote": "The free email service grew through viral marketing: every message carried an invitation to sign up.",
    "year": 1997,
    "source": {"kind": "article", "title": "Viral marketing", "publisher": "Example Business Review",
               "published_year": 1997, "url": "https://review.example.com/1997/viral-marketing"}
  }
}'::jsonb);

-- The demo moderator rejects the unverifiable usage.
select set_config('request.jwt.claims', '{"sub": "d0000000-0000-4000-8000-000000000002", "role": "authenticated"}', false);
select status from public.review_contribution(
  (select id from public.contributions
   where contributor_id = 'd0000000-0000-4000-8000-000000000001' and sense_id = 'mouse.n.04' and status = 'pending'
   limit 1),
  'reject',
  'The quote describes the device without using the word “mouse”. Please send one that names it.'
);

select set_config('request.jwt.claims', '', false);
