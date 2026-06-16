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
  const limitConfigs: { key: keyof GlobalLimits; label: string; color: string }[] = [
    { key: "voltage", label: "Voltage", color: "#f9e2af" },
    { key: "current", label: "Current", color: "#89b4fa" },
    { key: "power", label: "Power", color: "#a6e3a1" },
    { key: "frequency", label: "Frequency", color: "#fab387" },
  ];

  const hasAnyLimits = limitConfigs.some((config) => limits[config.key] !== undefined && limits[config.key] !== null);

  if (!hasAnyLimits) {
    return (
      <div className="safety-limits-panel empty">
        <p className="no-limits">No safety limits declared</p>
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
