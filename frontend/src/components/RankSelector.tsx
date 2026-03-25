import type { CertisRank } from "./rankData";
import { RANK_CARDS } from "./rankData";

type Props = {
  value: CertisRank | null;
  onChange: (rank: CertisRank) => void;
};

const ADMIN_APPROVAL_RANKS: CertisRank[] = ["SSS", "CSO"];

export function RankSelector({ value, onChange }: Props) {
  return (
    <div className="rank-selector-grid" role="radiogroup" aria-label="Select your rank">
      {RANK_CARDS.map((card) => {
        const needsAdmin = ADMIN_APPROVAL_RANKS.includes(card.id);
        const selected = value === card.id;
        const isGround = card.tier === "ground";

        return (
          <button
            key={card.id}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-disabled={needsAdmin}
            disabled={needsAdmin}
            title={needsAdmin ? "Requires admin approval — contact your supervisor" : undefined}
            className={[
              "rank-card",
              isGround ? "rank-card--ground" : "rank-card--supervisory",
              selected ? "rank-card--selected" : "",
              needsAdmin ? "rank-card--disabled" : "",
            ]
              .filter(Boolean)
              .join(" ")}
            onClick={() => {
              if (!needsAdmin) onChange(card.id);
            }}
          >
            {needsAdmin && <span className="rank-card__badge">Requires admin approval</span>}
            {selected && !needsAdmin && (
              <span className="rank-card__check" aria-hidden>
                ✓
              </span>
            )}
            <span className="rank-card__abbr">{card.id}</span>
            <span className="rank-card__title">{card.title}</span>
            <ul className="rank-card__duties">
              {card.responsibilities.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </button>
        );
      })}
    </div>
  );
}
