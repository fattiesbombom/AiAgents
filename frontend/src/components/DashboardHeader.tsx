import type { UserProfile } from "../lib/api";
import { RankBadge } from "./RankBadge";

type Props = {
  profile: UserProfile;
  title: string;
  subtitle?: string;
  onLogout: () => void;
  logoutLoading?: boolean;
};

export function DashboardHeader({ profile, title, subtitle, onLogout, logoutLoading }: Props) {
  return (
    <header className="db-header">
      <div className="db-header__brand">
        <span className="certis-brand__mark certis-brand__mark--sm">Certis</span>
        <div>
          <h1 className="db-header__title">{title}</h1>
          {subtitle && <p className="db-header__sub subtle">{subtitle}</p>}
        </div>
      </div>
      <div className="db-header__user">
        <div className="db-header__who">
          <span className="db-header__name">{profile.full_name || "Officer"}</span>
          <RankBadge rank={profile.rank} roleType={profile.role_type} roleLabel={profile.role_label} />
          <span className="subtle db-header__zone">
            Zone: {profile.assigned_zone?.trim() ? profile.assigned_zone : "Unassigned"}
          </span>
        </div>
        <button type="button" className="btn btn-ghost db-header__logout" disabled={logoutLoading} onClick={onLogout}>
          {logoutLoading ? "Signing out…" : "Log out"}
        </button>
      </div>
    </header>
  );
}
