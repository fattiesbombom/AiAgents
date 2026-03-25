import { RANK_CARDS, type CertisRank } from "./rankData";

type Props = { rank: CertisRank };

export function RankBadge({ rank }: Props) {
  const tier = RANK_CARDS.find((c) => c.id === rank)?.tier ?? "ground";
  const cls =
    tier === "ground" ? "rank-badge rank-badge--ground" : "rank-badge rank-badge--supervisory";
  return (
    <span className={cls} title={RANK_CARDS.find((c) => c.id === rank)?.title}>
      {rank}
    </span>
  );
}

export function isSupervisorRank(rank: CertisRank): boolean {
  return rank === "SS" || rank === "SSS" || rank === "CSO";
}

/** SS+ may approve human review / escalation (SSO is read-only in SCC queue). */
export function canSccApproveReview(rank: CertisRank): boolean {
  return rank === "SS" || rank === "SSS" || rank === "CSO";
}
