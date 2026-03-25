import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL;
const anon = import.meta.env.VITE_SUPABASE_ANON_KEY;

if (!url || !anon) {
  console.warn(
    "[Certis] VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY is missing. Auth pages will not work until set in .env",
  );
}

export const supabase = createClient(url ?? "", anon ?? "", {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
  },
});

export function isSupabaseConfigured(): boolean {
  return Boolean(url?.trim() && anon?.trim());
}
