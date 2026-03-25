import { useQuery } from "@tanstack/react-query";
import type { Session } from "@supabase/supabase-js";
import type { UserProfile } from "../lib/api";
import { coerceStaffRoleType, parseCertisRank } from "../lib/api";
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
      if (!data || typeof data !== "object") return null;
      const row = data as Record<string, unknown>;
      const ta = row.todays_assignment;
      const todays_assignment =
        ta === "ground" || ta === "command_centre" ? ta : null;
      const asg = row.assignment_set_at;
      const role_type = coerceStaffRoleType(row.role_type);
      const parsedRank = parseCertisRank(row.rank);
      const rank =
        parsedRank ?? (role_type === "security_officer" ? "SO" : null);
      return {
        id: String(row.id),
        role_type,
        rank,
        role_label: typeof row.role_label === "string" ? row.role_label : "Officer",
        deployment_type:
          row.deployment_type === "ground" || row.deployment_type === "command_centre"
            ? row.deployment_type
            : null,
        todays_assignment,
        assignment_set_at: typeof asg === "string" ? asg : null,
        assigned_zone: typeof row.assigned_zone === "string" ? row.assigned_zone : null,
        full_name: typeof row.full_name === "string" ? row.full_name : null,
        badge_id: typeof row.badge_id === "string" ? row.badge_id : null,
      } satisfies UserProfile;
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
