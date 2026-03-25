export type CertisRank = "SO" | "SSO" | "SS" | "SSS" | "CSO";

export type RankTier = "ground" | "supervisory";

export type RankCardDef = {
  id: CertisRank;
  title: string;
  tier: RankTier;
  responsibilities: [string, string, string];
};

/** Certis hierarchy — ground (blue) vs supervisory (orange) in UI. */
export const RANK_CARDS: RankCardDef[] = [
  {
    id: "SO",
    title: "Security Officer",
    tier: "ground",
    responsibilities: [
      "Screening, patrol, and access control",
      "First response and incident reporting",
      "Follow dispatch and SOPs on the ground",
    ],
  },
  {
    id: "SSO",
    title: "Senior Security Officer",
    tier: "ground",
    responsibilities: [
      "SCC / FCC operations support",
      "CCTV monitoring and key management",
      "Traffic regulation and elevated patrol tasks",
    ],
  },
  {
    id: "SS",
    title: "Security Supervisor",
    tier: "supervisory",
    responsibilities: [
      "SCC / FCC supervision and incident management",
      "Direct supervision and ground dispatch",
      "Escalation decisions within scope",
    ],
  },
  {
    id: "SSS",
    title: "Senior Security Supervisor",
    tier: "supervisory",
    responsibilities: [
      "Audits and compliance checks",
      "Risk assessment and quality oversight",
      "Broader supervisory coverage",
    ],
  },
  {
    id: "CSO",
    title: "Chief Security Officer",
    tier: "supervisory",
    responsibilities: [
      "Supervision management",
      "Contingency and crisis planning",
      "Strategic security direction",
    ],
  },
];

export function roleLabelForRank(rank: CertisRank): string {
  const row = RANK_CARDS.find((r) => r.id === rank);
  return row?.title ?? "Security Officer";
}
