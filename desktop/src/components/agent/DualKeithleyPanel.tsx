import { useEffect, useMemo, useState } from "react";
import {
  API_BASE,
  AgentRunSummary,
  AgentRunsResponse,
  ConnectedInstrument,
  DualKeithleyPlanResponse,
  DualKeithleyRun,
  SweepConfig,
} from "../../types";

interface DualKeithleyPanelProps {
  connected: ConnectedInstrument[];
}

const DEFAULT_SOURCE_SCHEMA = "keithley/smu/2600";
const DEFAULT_METER_SCHEMA = "keithley/dmm/dmm6500";

function toNumber(value: string): number {
  return Number.parseFloat(value);
}

function formatNumber(value: number | null): string {
  if (value === null) return "-";
  if (Math.abs(value) >= 1) return value.toFixed(6);
  return value.toExponential(6);
}

function detectAddress(
  connected: ConnectedInstrument[],
  category: "smu" | "dmm",
): string {
  const match = connected.find((inst) => inst.schema_key?.includes(`/${category}/`));
  return match?.address ?? "";
}

function DualSweepChart({ run }: { run: DualKeithleyRun | null }) {
  const points = run?.result?.points ?? [];
  const width = 640;
  const height = 280;
  const margin = { top: 20, right: 24, bottom: 42, left: 64 };
  const chartWidth = width - margin.left - margin.right;
  const chartHeight = height - margin.top - margin.bottom;

  if (points.length === 0) {
    return (
      <div className="dual-chart empty">
        <svg viewBox={`0 0 ${width} ${height}`}>
          <text x={width / 2} y={height / 2} textAnchor="middle">
            No dual sweep data
          </text>
        </svg>
      </div>
    );
  }

  const xValues = points.map((point) => point.source_voltage);
  const yValues = points.map((point) => point.meter_value);
  const xMin = Math.min(...xValues);
  const xMax = Math.max(...xValues);
  const yMin = Math.min(...yValues);
  const yMax = Math.max(...yValues);
  const xRange = xMax === xMin ? 1 : xMax - xMin;
  const yRange = yMax === yMin ? 1 : yMax - yMin;
  const xScale = (value: number) => margin.left + ((value - xMin) / xRange) * chartWidth;
  const yScale = (value: number) =>
    margin.top + chartHeight - ((value - yMin) / yRange) * chartHeight;
  const path = points
    .map((point, index) => {
      const command = index === 0 ? "M" : "L";
      return `${command} ${xScale(point.source_voltage)} ${yScale(point.meter_value)}`;
    })
    .join(" ");

  return (
    <div className="dual-chart">
      <svg viewBox={`0 0 ${width} ${height}`}>
        <line
          x1={margin.left}
          y1={margin.top + chartHeight}
          x2={margin.left + chartWidth}
          y2={margin.top + chartHeight}
        />
        <line
          x1={margin.left}
          y1={margin.top}
          x2={margin.left}
          y2={margin.top + chartHeight}
        />
        <path d={path} />
        {points.map((point, index) => (
          <circle
            key={`${point.timestamp}-${index}`}
            cx={xScale(point.source_voltage)}
            cy={yScale(point.meter_value)}
            r="3"
          />
        ))}
        <text x={margin.left + chartWidth / 2} y={height - 8} textAnchor="middle">
          Source Voltage (V)
        </text>
        <text x="16" y={margin.top + chartHeight / 2} textAnchor="middle">
          Meter Value
        </text>
      </svg>
    </div>
  );
}

export default function DualKeithleyPanel({ connected }: DualKeithleyPanelProps) {
  const [goal, setGoal] = useState(
    "Sweep 0V to 1V in 0.5V steps and measure DUT voltage with DMM6500",
  );
  const [sourceAddress, setSourceAddress] = useState(detectAddress(connected, "smu"));
  const [meterAddress, setMeterAddress] = useState(detectAddress(connected, "dmm"));
  const [sourceSchema, setSourceSchema] = useState(DEFAULT_SOURCE_SCHEMA);
  const [meterSchema, setMeterSchema] = useState(DEFAULT_METER_SCHEMA);
  const [startVoltage, setStartVoltage] = useState("0");
  const [stopVoltage, setStopVoltage] = useState("1");
  const [step, setStep] = useState("0.5");
  const [compliance, setCompliance] = useState("0.01");
  const [delayMs, setDelayMs] = useState("0");
  const [meterRange, setMeterRange] = useState("10");
  const [direction, setDirection] = useState<SweepConfig["direction"]>("UP");
  const [run, setRun] = useState<DualKeithleyRun | null>(null);
  const [runs, setRuns] = useState<AgentRunSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sourceAddress) {
      setSourceAddress(detectAddress(connected, "smu"));
    }
    if (!meterAddress) {
      setMeterAddress(detectAddress(connected, "dmm"));
    }
  }, [connected, meterAddress, sourceAddress]);

  const connectedOptions = useMemo(
    () => connected.filter((inst) => inst.schema_key),
    [connected],
  );

  const sourceConfig: SweepConfig = {
    start_voltage: toNumber(startVoltage),
    stop_voltage: toNumber(stopVoltage),
    step: toNumber(step),
    compliance: toNumber(compliance),
    delay_ms: Number.parseInt(delayMs, 10),
    direction,
  };

  const requestBody = {
    goal,
    source: {
      address: sourceAddress,
      instrument_key: sourceSchema,
    },
    meter: {
      address: meterAddress,
      instrument_key: meterSchema,
    },
    source_config: sourceConfig,
    meter_config: {
      function: "VOLT:DC",
      range: toNumber(meterRange),
    },
  };

  const applyRun = (nextRun: DualKeithleyRun) => {
    setRun(nextRun);
    setGoal(nextRun.plan.goal);
    setSourceAddress(nextRun.plan.source.address);
    setMeterAddress(nextRun.plan.meter.address);
    setSourceSchema(nextRun.plan.source.instrument_key);
    setMeterSchema(nextRun.plan.meter.instrument_key);
    setStartVoltage(String(nextRun.plan.source_config.start_voltage));
    setStopVoltage(String(nextRun.plan.source_config.stop_voltage));
    setStep(String(nextRun.plan.source_config.step));
    setCompliance(String(nextRun.plan.source_config.compliance));
    setDelayMs(String(nextRun.plan.source_config.delay_ms));
    setDirection(nextRun.plan.source_config.direction);
    setMeterRange(String(nextRun.plan.meter_config.range));
  };

  const refreshRuns = async () => {
    try {
      const response = await fetch(`${API_BASE}/agent/runs`);
      if (!response.ok) return;
      const data = (await response.json()) as AgentRunsResponse;
      setRuns(data.runs.filter((item) => item.experiment_type === "dual_keithley_sweep"));
    } catch {
      // History is optional; keep the main workflow usable when unavailable.
    }
  };

  useEffect(() => {
    refreshRuns();
  }, []);

  const requestRun = async (path: string, body: unknown): Promise<DualKeithleyRun> => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = (await response.json().catch(() => ({}))) as Partial<DualKeithleyPlanResponse> & {
        detail?: string;
      };
      if (!response.ok || !data.run) {
        throw new Error(data.detail ?? `Request failed: ${response.status}`);
      }
      applyRun(data.run);
      await refreshRuns();
      return data.run;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
      throw err;
    } finally {
      setBusy(false);
    }
  };

  const handlePlan = async () => {
    await requestRun("/agent/multi/plan", requestBody);
  };

  const handleAiPlan = async () => {
    await requestRun("/agent/llm/plan", {
      goal,
      experiment_type: "dual_keithley_sweep",
    });
  };

  const handleDryRun = async () => {
    const planned = run ?? (await requestRun("/agent/multi/plan", requestBody));
    await requestRun("/agent/multi/dry-run", { run_id: planned.run_id });
  };

  const handleExecute = async () => {
    let executable = run;
    if (!executable) {
      executable = await requestRun("/agent/multi/plan", requestBody);
    }
    if (!executable.validation) {
      executable = await requestRun("/agent/multi/dry-run", { run_id: executable.run_id });
    }
    await requestRun("/agent/multi/execute", {
      run_id: executable.run_id,
      confirm: true,
    });
  };

  const handleExport = () => {
    if (!run?.result) return;
    window.open(`${API_BASE}/agent/multi/runs/${run.run_id}/export`, "_blank");
  };

  const handleLoadRun = async (runId: string) => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/agent/multi/runs/${runId}`);
      const data = (await response.json().catch(() => ({}))) as Partial<DualKeithleyPlanResponse> & {
        detail?: string;
      };
      if (!response.ok || !data.run) {
        throw new Error(data.detail ?? `Load failed: ${response.status}`);
      }
      applyRun(data.run);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Load failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="dual-keithley-panel">
      <section className="dual-config panel">
        <h2>Keithley Dual Sweep</h2>
        <label>
          Goal
          <textarea value={goal} onChange={(event) => setGoal(event.target.value)} />
        </label>
        <div className="dual-grid">
          <label>
            2600 address
            <input
              list="connected-addresses"
              value={sourceAddress}
              onChange={(event) => setSourceAddress(event.target.value)}
            />
          </label>
          <label>
            DMM6500 address
            <input
              list="connected-addresses"
              value={meterAddress}
              onChange={(event) => setMeterAddress(event.target.value)}
            />
          </label>
          <label>
            Source schema
            <input value={sourceSchema} onChange={(event) => setSourceSchema(event.target.value)} />
          </label>
          <label>
            Meter schema
            <input value={meterSchema} onChange={(event) => setMeterSchema(event.target.value)} />
          </label>
          <label>
            Start V
            <input value={startVoltage} onChange={(event) => setStartVoltage(event.target.value)} />
          </label>
          <label>
            Stop V
            <input value={stopVoltage} onChange={(event) => setStopVoltage(event.target.value)} />
          </label>
          <label>
            Step V
            <input value={step} onChange={(event) => setStep(event.target.value)} />
          </label>
          <label>
            Compliance A
            <input value={compliance} onChange={(event) => setCompliance(event.target.value)} />
          </label>
          <label>
            Delay ms
            <input value={delayMs} onChange={(event) => setDelayMs(event.target.value)} />
          </label>
          <label>
            Meter range
            <input value={meterRange} onChange={(event) => setMeterRange(event.target.value)} />
          </label>
          <label>
            Direction
            <select
              value={direction}
              onChange={(event) => setDirection(event.target.value as SweepConfig["direction"])}
            >
              <option value="UP">UP</option>
              <option value="DOWN">DOWN</option>
              <option value="BOTH">BOTH</option>
            </select>
          </label>
        </div>
        <datalist id="connected-addresses">
          {connectedOptions.map((inst) => (
            <option key={inst.address} value={inst.address}>
              {inst.schema_key}
            </option>
          ))}
        </datalist>
        <div className="dual-actions">
          <button onClick={handleAiPlan} disabled={busy}>
            AI Plan
          </button>
          <button onClick={handlePlan} disabled={busy}>
            Plan
          </button>
          <button onClick={handleDryRun} disabled={busy}>
            Dry Run
          </button>
          <button onClick={handleExecute} disabled={busy}>
            Execute
          </button>
          <button onClick={handleExport} disabled={!run?.result}>
            Export CSV
          </button>
        </div>
        {error && <div className="sweep-error">{error}</div>}
      </section>

      <section className="dual-run panel">
        <h2>Run State</h2>
        <div className="dual-summary">
          <span>run: {run?.run_id ?? "-"}</span>
          <span>status: {run?.status ?? "idle"}</span>
          <span>points: {run?.validation?.estimated_points ?? run?.result?.summary.points ?? "-"}</span>
          <span>mean: {formatNumber(run?.result?.summary.mean ?? null)}</span>
        </div>
        {run?.validation && (
          <div className={`validation-result ${run.validation.valid ? "pass" : "fail"}`}>
            <div className="validation-header">
              {run.validation.valid ? "Validation passed" : "Validation blocked"}
            </div>
            {run.validation.issues.length > 0 && (
              <ul>
                {run.validation.issues.map((issue) => (
                  <li key={issue}>{issue}</li>
                ))}
              </ul>
            )}
          </div>
        )}
        <div className="dual-command-preview">
          <h3>Command Preview</h3>
          <div>
            <strong>2600</strong>
            <pre>{(run?.plan.commands.source ?? []).join("\n")}</pre>
          </div>
          <div>
            <strong>DMM6500</strong>
            <pre>{(run?.plan.commands.meter ?? []).join("\n")}</pre>
          </div>
        </div>
        <div className="dual-history">
          <div className="dual-history-header">
            <h3>Run Records</h3>
            <button onClick={refreshRuns} disabled={busy}>
              Refresh
            </button>
          </div>
          <ul>
            {runs.slice(0, 8).map((item) => (
              <li key={item.run_id}>
                <button onClick={() => handleLoadRun(item.run_id)} disabled={busy}>
                  <span>{item.run_id}</span>
                  <span>{item.status}</span>
                  <small>{item.goal}</small>
                </button>
              </li>
            ))}
            {runs.length === 0 && <li className="dual-history-empty">No recorded runs</li>}
          </ul>
        </div>
      </section>

      <section className="dual-results panel">
        <h2>Result</h2>
        <DualSweepChart run={run} />
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Source Voltage (V)</th>
                <th>Meter Value</th>
                <th>Timestamp</th>
              </tr>
            </thead>
            <tbody>
              {(run?.result?.points ?? []).map((point, index) => (
                <tr key={`${point.timestamp}-${index}`}>
                  <td>{point.source_voltage.toFixed(6)}</td>
                  <td>{point.meter_value.toExponential(6)}</td>
                  <td>{new Date(point.timestamp).toLocaleTimeString()}</td>
                </tr>
              ))}
              {!run?.result && (
                <tr className="no-data">
                  <td colSpan={3}>No data</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
