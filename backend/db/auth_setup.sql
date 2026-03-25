-- Supabase Auth + Certis profiles (run in Supabase SQL Editor).
-- Requires: project with Auth enabled.
--
-- After creating ``public.profiles``, enable it for the Data API if needed:
-- Dashboard → Settings → API → Expose ``profiles`` under Schema ``public`` (or use SQL grants).

-- ---------------------------------------------------------------------------
-- 1) Base table (fresh installs)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.profiles (
  id UUID PRIMARY KEY REFERENCES auth.users (id) ON DELETE CASCADE,
  role_type VARCHAR NOT NULL DEFAULT 'security_officer',
  rank VARCHAR,
  role_label VARCHAR NOT NULL DEFAULT 'Security Officer',
  deployment_type VARCHAR,
  todays_assignment VARCHAR,
  assignment_set_at TIMESTAMPTZ,
  assigned_zone VARCHAR,
  badge_id VARCHAR UNIQUE,
  full_name VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- 2) Legacy upgrades (idempotent)
-- ---------------------------------------------------------------------------
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS role_type VARCHAR;
UPDATE public.profiles SET role_type = 'security_officer' WHERE role_type IS NULL;
ALTER TABLE public.profiles ALTER COLUMN role_type SET DEFAULT 'security_officer';
ALTER TABLE public.profiles ALTER COLUMN role_type SET NOT NULL;

ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS todays_assignment VARCHAR;
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS assignment_set_at TIMESTAMPTZ;

ALTER TABLE public.profiles ALTER COLUMN rank DROP NOT NULL;
ALTER TABLE public.profiles ALTER COLUMN deployment_type DROP NOT NULL;

ALTER TABLE public.profiles DROP CONSTRAINT IF EXISTS profiles_role_type_check;
ALTER TABLE public.profiles ADD CONSTRAINT profiles_role_type_check
  CHECK (role_type IN ('security_officer', 'auxiliary_police', 'enforcement_officer'));

ALTER TABLE public.profiles DROP CONSTRAINT IF EXISTS profiles_todays_assignment_check;
ALTER TABLE public.profiles ADD CONSTRAINT profiles_todays_assignment_check
  CHECK (todays_assignment IS NULL OR todays_assignment IN ('ground', 'command_centre'));

ALTER TABLE public.profiles DROP CONSTRAINT IF EXISTS profiles_rank_check;
ALTER TABLE public.profiles ADD CONSTRAINT profiles_rank_check
  CHECK (rank IS NULL OR rank IN ('SO', 'SSO', 'SS', 'SSS', 'CSO'));

ALTER TABLE public.profiles DROP CONSTRAINT IF EXISTS profiles_deployment_type_check;
ALTER TABLE public.profiles ADD CONSTRAINT profiles_deployment_type_check
  CHECK (deployment_type IS NULL OR deployment_type IN ('ground', 'command_centre'));

ALTER TABLE public.profiles DROP CONSTRAINT IF EXISTS profiles_rank_role_type_check;
ALTER TABLE public.profiles ADD CONSTRAINT profiles_rank_role_type_check
  CHECK (role_type = 'security_officer' OR rank IS NULL);

CREATE INDEX IF NOT EXISTS profiles_badge_id_idx ON public.profiles (badge_id);
CREATE INDEX IF NOT EXISTS profiles_assigned_zone_idx ON public.profiles (assigned_zone);

COMMENT ON TABLE public.profiles IS 'Certis operator profile; synced from auth sign-up metadata via trigger.';

-- ---------------------------------------------------------------------------
-- 3) Auto-create profile on sign-up
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_role_type text;
  v_rank text;
  v_deploy text;
  v_role_label text;
BEGIN
  v_role_type := NULLIF(LOWER(TRIM(NEW.raw_user_meta_data->>'role_type')), '');
  IF v_role_type IS NULL OR v_role_type NOT IN ('security_officer', 'auxiliary_police', 'enforcement_officer') THEN
    v_role_type := 'security_officer';
  END IF;

  IF v_role_type = 'security_officer' THEN
    v_rank := COALESCE(NULLIF(TRIM(NEW.raw_user_meta_data->>'rank'), ''), 'SO');
    IF v_rank NOT IN ('SO', 'SSO', 'SS', 'SSS', 'CSO') THEN
      v_rank := 'SO';
    END IF;

    v_deploy := COALESCE(NULLIF(TRIM(NEW.raw_user_meta_data->>'deployment_type'), ''), 'ground');
    IF v_deploy NOT IN ('ground', 'command_centre') THEN
      v_deploy := 'ground';
    END IF;

    v_role_label := COALESCE(
      NULLIF(TRIM(NEW.raw_user_meta_data->>'role_label'), ''),
      CASE v_rank
        WHEN 'SO' THEN 'Security Officer'
        WHEN 'SSO' THEN 'Senior Security Officer'
        WHEN 'SS' THEN 'Security Supervisor'
        WHEN 'SSS' THEN 'Senior Security Supervisor'
        WHEN 'CSO' THEN 'Chief Security Officer'
        ELSE 'Security Officer'
      END
    );

    INSERT INTO public.profiles (
      id, role_type, rank, role_label, deployment_type,
      todays_assignment, assignment_set_at,
      assigned_zone, badge_id, full_name
    )
    VALUES (
      NEW.id,
      v_role_type,
      v_rank,
      v_role_label,
      v_deploy,
      NULL,
      NULL,
      NULLIF(TRIM(NEW.raw_user_meta_data->>'assigned_zone'), ''),
      NULLIF(TRIM(NEW.raw_user_meta_data->>'badge_id'), ''),
      NULLIF(TRIM(NEW.raw_user_meta_data->>'full_name'), '')
    );
  ELSE
    v_role_label := COALESCE(
      NULLIF(TRIM(NEW.raw_user_meta_data->>'role_label'), ''),
      CASE v_role_type
        WHEN 'auxiliary_police' THEN 'Auxiliary Police Officer'
        WHEN 'enforcement_officer' THEN 'Enforcement Officer'
        ELSE 'Officer'
      END
    );

    INSERT INTO public.profiles (
      id, role_type, rank, role_label, deployment_type,
      todays_assignment, assignment_set_at,
      assigned_zone, badge_id, full_name
    )
    VALUES (
      NEW.id,
      v_role_type,
      NULL,
      v_role_label,
      NULL,
      NULL,
      NULL,
      NULLIF(TRIM(NEW.raw_user_meta_data->>'assigned_zone'), ''),
      NULLIF(TRIM(NEW.raw_user_meta_data->>'badge_id'), ''),
      NULLIF(TRIM(NEW.raw_user_meta_data->>'full_name'), '')
    );
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW
  EXECUTE FUNCTION public.handle_new_user();

-- ---------------------------------------------------------------------------
-- 4) Row Level Security — profiles
-- ---------------------------------------------------------------------------
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS profiles_select_own ON public.profiles;
CREATE POLICY profiles_select_own
  ON public.profiles
  FOR SELECT
  TO authenticated
  USING (auth.uid() = id);

DROP POLICY IF EXISTS profiles_update_own ON public.profiles;
CREATE POLICY profiles_update_own
  ON public.profiles
  FOR UPDATE
  TO authenticated
  USING (auth.uid() = id)
  WITH CHECK (auth.uid() = id);

-- Service role bypasses RLS (used by backend MCP with SUPABASE_SERVICE_ROLE_KEY).
