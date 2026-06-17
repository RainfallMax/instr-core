import { useTranslation } from "react-i18next";
import { GlobalLimits, LimitDef } from "../types";

interface SafetyLimitsPanelProps {
  limits: GlobalLimits;
}

interface LimitCardProps {
  label: string;
  limit: LimitDef;
  borderColor: string;
}

function LimitCard({ label, limit, borderColor }: LimitCardProps) {
  return (
    <div className="limit-card" style={{ borderLeftColor: borderColor }}>
      <div className="limit-label">{label}</div>
      <div className="limit-value">
        {limit.max} <span className="limit-unit">{limit.unit}</span>
      </div>
    </div>
  );
}

export default function SafetyLimitsPanel({ limits }: SafetyLimitsPanelProps) {
  const { t } = useTranslation();
  const limitConfigs: { key: keyof GlobalLimits; label: string; color: string }[] = [
    { key: "voltage", label: t("schema.voltage"), color: "#d4d4d8" },
    { key: "current", label: t("schema.current"), color: "#a1a1aa" },
    { key: "power", label: t("schema.power"), color: "#fafafa" },
    { key: "frequency", label: t("schema.frequency"), color: "#71717a" },
  ];

  const hasAnyLimits = limitConfigs.some((config) => limits[config.key] !== undefined && limits[config.key] !== null);

  if (!hasAnyLimits) {
    return (
      <div className="safety-limits-panel empty">
        <p className="no-limits">{t("schema.noLimits")}</p>
      </div>
    );
  }

  return (
    <div className="safety-limits-panel">
      <div className="limits-grid">
        {limitConfigs.map((config) => {
          const limit = limits[config.key];
          if (!limit) return null;
          return (
            <LimitCard
              key={config.key}
              label={config.label}
              limit={limit}
              borderColor={config.color}
            />
          );
        })}
      </div>
    </div>
  );
}
