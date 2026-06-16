import { ConnectedPanelProps } from "../types";

export default function ConnectedPanel({
  connected,
  selected,
  onSelect,
  onBrowseSchema,
  onOpenTerminal,
}: ConnectedPanelProps) {
  return (
    <section className="panel">
      <h2>Connected</h2>
      <ul className="list">
        {connected.map((inst) => (
          <li key={inst.address} className="list-item">
            <label>
              <input
                type="radio"
                name="selected"
                value={inst.address}
                checked={selected === inst.address}
                onChange={() => onSelect(inst.address)}
              />
              <strong>
                {inst.manufacturer} {inst.model}
              </strong>
              <span className="addr">{inst.address}</span>
              <span className="idn">{inst.idn}</span>
              {inst.schema_key ? (
                <span className="schema-tag">
                  {inst.manufacturer} {inst.model} ({inst.schema_key})
                </span>
              ) : (
                <span className="no-schema-hint">No schema matched</span>
              )}
            </label>
            {inst.schema_key && (
              <div className="instrument-actions">
                <button
                  className="action-btn browse"
                  onClick={() => onBrowseSchema?.(inst.schema_key!)}
                >
                  Browse Schema
                </button>
                <button
                  className="action-btn terminal"
                  onClick={() => onOpenTerminal?.(inst.address)}
                >
                  Terminal
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
