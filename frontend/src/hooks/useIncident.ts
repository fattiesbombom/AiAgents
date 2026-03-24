import { useQuery } from "@tanstack/react-query";
import { getIncident } from "../lib/api";

export function useIncident(incidentId: string) {
  return useQuery({
    queryKey: ["incident", incidentId],
    queryFn: () => getIncident(incidentId),
    enabled: incidentId.trim().length > 0,
    refetchInterval: 5000,
  });
}
