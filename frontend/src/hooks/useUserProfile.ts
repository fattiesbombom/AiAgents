import { useQuery } from "@tanstack/react-query";
import type { Session } from "@supabase/supabase-js";
import type { UserProfile } from "../lib/api";
import { isSupabaseConfigured, supabase } from "../lib/supabase";

export type UserProfileBundle = {
  session: Session | null;
  profile: UserProfile | null;
};

export function useUserProfile() {
  const configured = isSupabaseConfigured();

  const sessionQuery = useQuery({
    queryKey: ["supabase-session"],
    queryFn: async () => {
      const { data, error } = await supabase.auth.getSession();
      if (error) throw error;
      return data.session ?? null;
    },
    enabled: configured,
    retry: 1,
  });

  const uid = sessionQuery.data?.user?.id;

  const profileQuery = useQuery({
    queryKey: ["profile", uid ?? "anonymous"],
    queryFn: async () => {
      if (!uid) return null;
      const { data, error } = await supabase.from("profiles").select("*").eq("id", uid).maybeSingle();
      if (error) throw error;
      return data as UserProfile | null;
    },
    enabled: Boolean(uid),
    retry: 1,
  });

  const loading = sessionQuery.isPending || (!!uid && profileQuery.isPending);
  const error =
    (sessionQuery.error as Error | null) ?? (profileQuery.error as Error | null) ?? null;

  return {
    session: sessionQuery.data ?? null,
    profile: profileQuery.data ?? null,
    loading,
    error,
    refetch: async () => {
      await Promise.all([sessionQuery.refetch(), profileQuery.refetch()]);
    },
  };
}
