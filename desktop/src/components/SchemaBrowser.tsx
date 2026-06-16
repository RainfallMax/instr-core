import { useEffect, useState } from "react";
import { API_BASE, InstrumentSchema, SchemaBrowserProps } from "../types";
import SchemaCommandTree from "./SchemaCommandTree";
import SafetyLimitsPanel from "./SafetyLimitsPanel";

export default function SchemaBrowser({ schemaKey, onSelectCommand }: SchemaBrowserProps) {
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
        setError(err instanceof Error ? err.message : "Failed to load schema");
      })
      .finally(() => {
        setLoading(false);
      });
  }, [schemaKey]);

  if (!schemaKey) {
    return (
      <div className="schema-browser empty">
        <p className="empty-message">Select an instrument schema to browse</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="schema-browser loading">
        <p className="loading-message">Loading schema...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="schema-browser error">
        <p className="error-message">Error: {error}</p>
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
              Firmware: {instrument.firmware_version}
            </span>
          )}
          {instrument.series && (
            <span className="meta-item">Series: {instrument.series}</span>
          )}
          {instrument.category && (
            <span className="meta-item">Category: {instrument.category}</span>
          )}
        </div>
      </div>

      <div className="schema-sections">
        <section className="schema-section">
          <h3 className="section-title">Command Tree</h3>
          <SchemaCommandTree
            commands={commands}
            onSelectCommand={(cmd) => onSelectCommand?.(cmd)}
          />
        </section>

        <section className="schema-section">
          <h3 className="section-title">Safety Limits</h3>
          <SafetyLimitsPanel limits={global_limits} />
        </section>
      </div>
    </div>
  );
}
