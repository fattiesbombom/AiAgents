-- Demo / development: seed Certis profiles after Auth users exist.
--
-- 1) Create five test users in Supabase Dashboard → Authentication (or sign-up API)
--    and copy each user UUID.
-- 2) Replace the UUIDs below with those values.
-- 3) Run this script in the SQL Editor.
--
-- If a profile row already exists for an id (e.g. trigger ran on sign-up), use
-- UPDATE instead of INSERT, or DELETE FROM public.profiles WHERE id = ... first.

-- Example (disabled): uncomment and substitute real auth.users ids.

-- INSERT INTO public.profiles (id, rank, role_label, deployment_type, assigned_zone, badge_id, full_name)
-- VALUES
--   ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'SO',  'Security Officer',               'ground',          'Zone-A', 'BADGE-SO-001',  'Test SO'),
--   ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'SSO', 'Senior Security Officer',        'command_centre',  'Zone-A', 'BADGE-SSO-001', 'Test SSO'),
--   ('cccccccc-cccc-cccc-cccc-cccccccccccc', 'SS',  'Security Supervisor',            'command_centre',  'Zone-A', 'BADGE-SS-001',  'Test SS'),
--   ('dddddddd-dddd-dddd-dddd-dddddddddddd', 'SSS', 'Senior Security Supervisor',     'command_centre',  'Zone-B', 'BADGE-SSS-001', 'Test SSS'),
--   ('eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee', 'CSO', 'Chief Security Officer',         'command_centre',  NULL,     'BADGE-CSO-001', 'Test CSO')
-- ON CONFLICT (id) DO UPDATE SET
--   rank = EXCLUDED.rank,
--   role_label = EXCLUDED.role_label,
--   deployment_type = EXCLUDED.deployment_type,
--   assigned_zone = EXCLUDED.assigned_zone,
--   badge_id = EXCLUDED.badge_id,
--   full_name = EXCLUDED.full_name;

-- Upsert helper: sync profile rank/zone without touching auth.users
-- (use when trigger already created a row with defaults).

-- UPDATE public.profiles SET rank = 'SSO', role_label = 'Senior Security Officer', deployment_type = 'command_centre'
-- WHERE id = 'your-user-uuid';
