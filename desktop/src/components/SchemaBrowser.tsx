import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { API_BASE, InstrumentSchema, SchemaBrowserProps } from "../types";
import SchemaCommandTree from "./SchemaCommandTree";
import SafetyLimitsPanel from "./SafetyLimitsPanel";

export default function SchemaBrowser({ schemaKey, onSelectCommand }: SchemaBrowserProps) {
  const { t } = useTranslation();
  const [schema, setSchema] = useState<InstrumentSchema | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!schemaKey) {
      setSchema(null);
      setError(null);
      return;
    }

    setLoading(true);
    setError(null);

    fetch(`${API_BASE}/instruments/${encodeURIComponent(schemaKey)}`)
      .then((res) => {
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}: ${res.statusText}`);
        }
        return res.json();
      })
      .then((data: InstrumentSchema) => {
        setSchema(data);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : t("schema.loadFailed"));
      })
      .finally(() => {
        setLoading(false);
      });
  }, [schemaKey]);

  if (!schemaKey) {
    return (
      <div className="schema-browser empty">
        <p className="empty-message">{t("schema.select")}</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="schema-browser loading">
        <p className="loading-message">{t("schema.loading")}</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="schema-browser error">
        <p className="error-message">{t("common.error")}: {error}</p>
      </div>
    );
  }

  if (!schema) {
    return null;
  }

  const { instrument, global_limits, commands } = schema;

  return (
    <div className="schema-browser">
      <div className="schema-header">
        <h2 className="schema-title">
          {instrument.manufacturer} {instrument.model}
        </h2>
        {instrument.description && (
          <p className="schema-description">{instrument.description}</p>
        )}
        <div className="schema-meta">
          {instrument.firmware_version && (
            <span className="meta-item">
              {t("schema.firmware")}: {instrument.firmware_version}
            </span>
          )}
          {instrument.series && (
            <span className="meta-item">{t("schema.series")}: {instrument.series}</span>
          )}
          {instrument.category && (
            <span className="meta-item">{t("schema.category")}: {instrument.category}</span>
          )}
        </div>
      </div>

      <div className="schema-sections">
        <section className="schema-section">
          <h3 className="section-title">{t("schema.commandTree")}</h3>
          <SchemaCommandTree
            commands={commands}
            onSelectCommand={(cmd) => onSelectCommand?.(cmd)}
          />
        </section>

        <section className="schema-section">
          <h3 className="section-title">{t("schema.safetyLimits")}</h3>
          <SafetyLimitsPanel limits={global_limits} />
        </section>
      </div>
    </div>
  );
}
