-- One-off repair for officer_daily_tasks (database must be security_output).
--
-- Run STEP 1 only first. If you see ANY error, stop — paste the full message.
-- Only after STEP 1 succeeds, run STEP 2 (or highlight only STEP 2 and execute).
--
-- If STEP 1 says "permission denied for schema public", connect as the postgres
-- superuser and run:  GRANT CREATE ON SCHEMA public TO YOUR_WINDOWS_LOGIN;

SET search_path TO public;

-- ========== STEP 1 ==========
DROP INDEX IF EXISTS public.officer_daily_tasks_lookup_idx;
DROP TABLE IF EXISTS public.officer_daily_tasks CASCADE;

CREATE TABLE public.officer_daily_tasks (
  id UUID PRIMARY KEY,
  task_date DATE NOT NULL,
  officer_rank VARCHAR NOT NULL,
  "zone" VARCHAR,
  task_type VARCHAR,
  "status" VARCHAR,
  description TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Optional check (should return 1 row):
-- SELECT * FROM public.officer_daily_tasks LIMIT 1;

-- ========== STEP 2 ==========
CREATE INDEX officer_daily_tasks_lookup_idx
  ON public.officer_daily_tasks (task_date, officer_rank, "zone");
