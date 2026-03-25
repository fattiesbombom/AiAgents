import { RANK_CARDS, type CertisRank } from "./rankData";
import type { StaffRoleType } from "../lib/api";

type Props = {
  rank: CertisRank | null;
  roleType?: StaffRoleType;
  roleLabel?: string;
};

function shortLabelForNonRank(roleType: StaffRoleType | undefined, roleLabel: string | undefined): string {
  if (roleType === "auxiliary_police") return "APO";
  if (roleType === "enforcement_officer") return "EO";
  const t = roleLabel?.trim();
  if (t) return t.length <= 6 ? t : `${t.slice(0, 5)}…`;
  return "Officer";
}

export function RankBadge({ rank, roleType, roleLabel }: Props) {
  if (!rank) {
    const short = shortLabelForNonRank(roleType, roleLabel);
    return (
      <span className="rank-badge rank-badge--ground" title={roleLabel?.trim() || short}>
        {short}
      </span>
    );
  }
  const tier = RANK_CARDS.find((c) => c.id === rank)?.tier ?? "ground";
  const cls =
    tier === "ground" ? "rank-badge rank-badge--ground" : "rank-badge rank-badge--supervisory";
  return (
    <span className={cls} title={RANK_CARDS.find((c) => c.id === rank)?.title}>
      {rank}
    </span>
  );
}

export function isSupervisorRank(rank: CertisRank | null | undefined): boolean {
  return rank === "SS" || rank === "SSS" || rank === "CSO";
}

/** SS+ may approve human review / escalation (SSO is read-only in SCC queue). */
export function canSccApproveReview(rank: CertisRank | null | undefined): boolean {
  return rank === "SS" || rank === "SSS" || rank === "CSO";
}
