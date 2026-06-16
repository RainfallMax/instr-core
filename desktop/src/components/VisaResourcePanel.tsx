import { useState } from "react";
import { API_BASE, ConnectedInstrument, VisaResourcePanelProps } from "../types";

export default function VisaResourcePanel({ onConnect }: VisaResourcePanelProps) {
  const [resources, setResources] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [connecting, setConnecting] = useState<string | null>(null);

  const scanResources = async () => {
    const res = await fetch(`${API_BASE}/visa/resources`);
    const data = await res.json();
    setResources(data);
  };

  const connectInstrument = async (address: string) => {
    setConnecting(address);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/visa/connect?address=${encodeURIComponent(address)}`, {
        method: "POST",
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Connection failed (${res.status})`);
      }

      const data: ConnectedInstrument = await res.json();
      onConnect(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Connection failed";
      setError(msg);
      // Auto-clear error after 5 seconds
      setTimeout(() => setError(null), 5000);
    } finally {
      setConnecting(null);
    }
  };

  return (
    <section className="panel">
      <h2>VISA Resources</h2>
      <button onClick={scanResources}>Scan</button>
      {error && (
        <div className="visa-error">{error}</div>
      )}
      <ul className="list">
        {resources.map((addr) => (
          <li key={addr} className="list-item visa-resource">
            <code>{addr}</code>
            <button
              onClick={() => connectInstrument(addr)}
              disabled={connecting === addr}
            >
              {connecting === addr ? "Connecting..." : "Connect"}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
