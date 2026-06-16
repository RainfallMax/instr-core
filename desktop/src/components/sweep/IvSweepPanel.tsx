import { useState, useEffect, useCallback, useRef } from "react";
import {
  API_BASE,
  ConnectedInstrument,
  SweepConfig,
  SweepPoint,
  SweepHistoryItem,
  SweepStatusResponse,
} from "../../types";
import SweepConfigForm from "./SweepConfigForm";
import SweepChart from "./SweepChart";
import SweepDataTable from "./SweepDataTable";
import SweepHistory from "./SweepHistory";

interface IvSweepPanelProps {
  connected: ConnectedInstrument[];
}

export default function IvSweepPanel({ connected }: IvSweepPanelProps) {
  const [config, setConfig] = useState<SweepConfig>({
    start_voltage: 0,
    stop_voltage: 10,
    step: 0.5,
    compliance: 0.01,
    delay_ms: 10,
    direction: "UP",
  });
  const [sweepId, setSweepId] = useState<string | null>(null);
  const [status, setStatus] = useState<
    "idle" | "running" | "completed" | "aborted" | "error"
  >("idle");
  const [points, setPoints] = useState<SweepPoint[]>([]);
  const [progress, setProgress] = useState<{ current: number; total: number }>({
    current: 0,
    total: 0,
  });
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<SweepHistoryItem[]>([]);

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const receivedCountRef = useRef(0);

  // Fetch history
  const fetchHistory = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/sweep/history`);
      if (!res.ok) return;
      const data = await res.json();
      setHistory(data.sessions || []);
    } catch {
      // silently fail
    }
  }, []);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  // Polling logic
  useEffect(() => {
    if (status !== "running" || !sweepId) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      return;
    }

    intervalRef.current = setInterval(async () => {
      try {
        const since = receivedCountRef.current;
        const res = await fetch(`${API_BASE}/sweep/${sweepId}/status?since_index=${since}`);
        if (!res.ok) throw new Error("Failed to fetch status");
        const data: SweepStatusResponse = await res.json();

        // 增量追加（后端只返回新点）
        const newPoints = data.new_points || [];
        if (newPoints.length > 0) {
          setPoints((prev) => [...prev, ...newPoints]);
          receivedCountRef.current = since + newPoints.length;
        }

        setStatus(data.status as typeof status);
        setProgress(data.progress);
        if (data.error_message) {
          setError(data.error_message);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Polling error");
      }
    }, 200);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [status, sweepId]);

  // Refresh history when sweep completes or errors
  useEffect(() => {
    if (status === "completed" || status === "aborted" || status === "error") {
      fetchHistory();
    }
  }, [status, fetchHistory]);

  const getSelectedInstrument = (): ConnectedInstrument | null => {
    const inst = connected.find((c) => c.schema_key);
    return inst || null;
  };

  const handleStart = async () => {
    setError(null);
    const inst = getSelectedInstrument();
    if (!inst) {
      setError("No instrument selected. Please connect an instrument with a schema.");
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/sweep/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          instrument_key: inst.schema_key,
          address: inst.address,
          config,
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Start failed: ${res.status}`);
      }

      const data = await res.json();
      setSweepId(data.session_id);
      setStatus("running");
      setPoints([]);
      receivedCountRef.current = 0;  // 重置
      setProgress({ current: 0, total: data.total_points });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Start failed");
      setStatus("error");
    }
  };

  const handleStop = async () => {
    if (!sweepId) return;
    try {
      const res = await fetch(`${API_BASE}/sweep/${sweepId}/stop`, {
        method: "POST",
      });
      if (!res.ok) throw new Error("Stop failed");
      const data = await res.json();
      setStatus(data.status as typeof status);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Stop failed");
    }
  };

  const handleSelectHistory = async (sessionId: string) => {
    try {
      const res = await fetch(`${API_BASE}/sweep/${sessionId}/result`);
      if (!res.ok) return;
      const data = await res.json();
      setPoints(data.points || []);
      receivedCountRef.current = (data.points || []).length;  // 重置
      setStatus(data.status as typeof status);
      setSweepId(sessionId);
      setProgress({
        current: (data.points || []).length,
        total: (data.points || []).length,
      });
    } catch {
      // silently fail
    }
  };

  const handleExport = () => {
    if (!sweepId) return;
    window.open(`${API_BASE}/sweep/${sweepId}/export`, "_blank");
  };

  const canStart = !!getSelectedInstrument();

  return (
    <div className="sweep-panel">
      <div className="sweep-left">
        <SweepConfigForm
          config={config}
          onChange={setConfig}
          disabled={status === "running"}
          onStart={handleStart}
          onStop={handleStop}
          status={status}
          canStart={canStart}
          progress={progress}
        />
        {error && <div className="sweep-error">{error}</div>}
        <SweepHistory sessions={history} onSelect={handleSelectHistory} />
      </div>
      <div className="sweep-right">
        <SweepChart points={points} direction={config.direction} />
        <SweepDataTable points={points} />
        <div className="sweep-actions">
          <button onClick={handleExport} disabled={!sweepId}>
            Export CSV
          </button>
        </div>
      </div>
    </div>
  );
}
