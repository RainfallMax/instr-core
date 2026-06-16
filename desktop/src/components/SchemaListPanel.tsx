import { useState } from "react";
import { API_BASE, InstrumentMeta, SchemaListPanelProps } from "../types";

export default function SchemaListPanel({ onSelectSchema }: SchemaListPanelProps) {
  const [instruments, setInstruments] = useState<InstrumentMeta[]>([]);

  const loadInstruments = async () => {
    const res = await fetch(`${API_BASE}/instruments`);
    const data = await res.json();
    setInstruments(data);
  };

  return (
    <section className="panel">
      <h2>Instrument Schemas</h2>
      <button onClick={loadInstruments}>Load Registry</button>
      <ul className="list">
        {instruments.map((inst) => (
          <li
            key={inst.key}
            className="list-item"
            onClick={() => onSelectSchema?.(inst.key)}
            style={{ cursor: onSelectSchema ? "pointer" : "default" }}
          >
            <strong>
              {inst.manufacturer} {inst.model}
            </strong>
            <span className="key">{inst.key}</span>
            {inst.description && <span className="desc">{inst.description}</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}
