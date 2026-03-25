-- Supabase Auth + Certis profiles (run in Supabase SQL Editor).
-- Requires: project with Auth enabled.
--
-- After creating ``public.profiles``, enable it for the Data API if needed:
-- Dashboard → Settings → API → Expose ``profiles`` under Schema ``public`` (or use SQL grants).

-- ---------------------------------------------------------------------------
-- 1) Profiles (one row per auth user; source of truth for rank / zone / SCC)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.profiles (
  id UUID PRIMARY KEY REFERENCES auth.users (id) ON DELETE CASCADE,
  rank VARCHAR NOT NULL DEFAULT 'SO'
    CHECK (rank IN ('SO', 'SSO', 'SS', 'SSS', 'CSO')),
  role_label VARCHAR NOT NULL DEFAULT 'Security Officer',
  deployment_type VARCHAR NOT NULL DEFAULT 'ground'
    CHECK (deployment_type IN ('ground', 'command_centre')),
  assigned_zone VARCHAR,
  badge_id VARCHAR UNIQUE,
  full_name VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS profiles_badge_id_idx ON public.profiles (badge_id);
CREATE INDEX IF NOT EXISTS profiles_assigned_zone_idx ON public.profiles (assigned_zone);

COMMENT ON TABLE public.profiles IS 'Certis operator profile; synced from auth sign-up metadata via trigger.';

-- ---------------------------------------------------------------------------
-- 2) Auto-create profile on sign-up
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_rank text;
  v_deploy text;
BEGIN
  v_rank := COALESCE(NEW.raw_user_meta_data->>'rank', 'SO');
  IF v_rank NOT IN ('SO', 'SSO', 'SS', 'SSS', 'CSO') THEN
    v_rank := 'SO';
  END IF;

  v_deploy := COALESCE(NEW.raw_user_meta_data->>'deployment_type', 'ground');
  IF v_deploy NOT IN ('ground', 'command_centre') THEN
    v_deploy := 'ground';
  END IF;

  INSERT INTO public.profiles (id, rank, role_label, deployment_type, assigned_zone, badge_id, full_name)
  VALUES (
    NEW.id,
    v_rank,
    COALESCE(
      NULLIF(TRIM(NEW.raw_user_meta_data->>'role_label'), ''),
      CASE v_rank
        WHEN 'SO' THEN 'Security Officer'
        WHEN 'SSO' THEN 'Senior Security Officer'
        WHEN 'SS' THEN 'Security Supervisor'
        WHEN 'SSS' THEN 'Senior Security Supervisor'
        WHEN 'CSO' THEN 'Chief Security Officer'
        ELSE 'Security Officer'
      END
    ),
    v_deploy,
    NULLIF(TRIM(NEW.raw_user_meta_data->>'assigned_zone'), ''),
    NULLIF(TRIM(NEW.raw_user_meta_data->>'badge_id'), ''),
    NULLIF(TRIM(NEW.raw_user_meta_data->>'full_name'), '')
  );
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW
  EXECUTE PROCEDURE public.handle_new_user();

-- ---------------------------------------------------------------------------
-- 3) Row Level Security — profiles
-- ---------------------------------------------------------------------------
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;

-- Authenticated users can read their own profile (dashboard / mobile).
CREATE POLICY profiles_select_own
  ON public.profiles
  FOR SELECT
  TO authenticated
  USING (auth.uid() = id);

-- Optional: allow users to update non-privileged fields only if you expose PATCH;
-- keep rank changes admin-only in production (use service role or Edge Function).
CREATE POLICY profiles_update_own
  ON public.profiles
  FOR UPDATE
  TO authenticated
  USING (auth.uid() = id)
  WITH CHECK (auth.uid() = id);

-- Service role bypasses RLS (used by backend MCP with SUPABASE_SERVICE_ROLE_KEY).

-- ---------------------------------------------------------------------------
-- 4) Incident RLS (documented — apply if you replicate incidents into Supabase)
--
-- Your app’s canonical incidents may live on a separate OUTPUT Postgres.
-- If you add e.g. public.incidents_sync in Supabase, consider:
--
--   SO:        SELECT where incident is assigned to auth.uid() OR
--              user’s profile.assigned_zone matches incident.zone AND user is SO
--              (narrow “own dispatches” — adjust columns to your model).
--
--   SSO / SS:  SELECT where incident.zone (or location) matches
--              profiles.assigned_zone for auth.uid().
--
--   SSS / CSO: SELECT true (full read within org) or scope by site_id if multi-tenant.
--
-- Escalation approval remains enforced in the application (human_review API),
-- not only in RLS.
-- ---------------------------------------------------------------------------
