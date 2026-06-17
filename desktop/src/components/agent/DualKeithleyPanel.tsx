import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import * as echarts from "echarts/core";
import { GraphicComponent, GridComponent, TooltipComponent } from "echarts/components";
import { LineChart } from "echarts/charts";
import { CanvasRenderer } from "echarts/renderers";
import {
  API_BASE,
  AgentRunSummary,
  AgentRunsResponse,
  ConnectedInstrument,
  DualKeithleyPlanResponse,
  DualKeithleyRun,
  SweepConfig,
} from "../../types";
import { Button } from "../ui/Button";

echarts.use([GraphicComponent, GridComponent, TooltipComponent, LineChart, CanvasRenderer]);

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
  const { t } = useTranslation();
  const chartRef = useRef<HTMLDivElement | null>(null);
  const points = run?.result?.points ?? [];

  useEffect(() => {
    if (!chartRef.current) return;
    const chart = echarts.init(chartRef.current, "dark");
    chart.setOption({
      backgroundColor: "transparent",
      grid: { top: 28, right: 28, bottom: 48, left: 72 },
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "value",
        name: t("dual.sourceVoltage"),
        nameLocation: "middle",
        nameGap: 30,
        axisLine: { lineStyle: { color: "#a1a1aa" } },
        splitLine: { lineStyle: { color: "#262626" } },
      },
      yAxis: {
        type: "value",
        name: t("dual.meterValue"),
        nameLocation: "middle",
        nameGap: 48,
        axisLine: { lineStyle: { color: "#a1a1aa" } },
        splitLine: { lineStyle: { color: "#262626" } },
      },
      series: [{
        type: "line",
        symbol: "circle",
        symbolSize: 6,
        data: points.map((point) => [point.source_voltage, point.meter_value]),
        lineStyle: { width: 2, color: "#fafafa" },
        itemStyle: { color: "#fafafa" },
      }],
      graphic:
        points.length === 0
          ? {
              type: "text",
              left: "center",
              top: "middle",
              style: { text: t("dual.noDualData"), fill: "#71717a", fontSize: 14 },
            }
          : undefined,
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [points, t]);

  return <div className="dual-chart echarts-panel" ref={chartRef} />;
}

export default function DualKeithleyPanel({ connected }: DualKeithleyPanelProps) {
  const { t } = useTranslation();
  const [goal, setGoal] = useState(
    t("dual.defaultGoal"),
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
      setError(err instanceof Error ? err.message : t("common.requestFailed"));
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
      setError(err instanceof Error ? err.message : t("common.loadFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="dual-keithley-panel">
      <section className="dual-config panel">
        <h2>{t("dual.title")}</h2>
        <label>
          {t("dual.goal")}
          <textarea value={goal} onChange={(event) => setGoal(event.target.value)} />
        </label>
        <div className="dual-grid">
          <label>
            {t("dual.sourceAddress")}
            <input
              list="connected-addresses"
              value={sourceAddress}
              onChange={(event) => setSourceAddress(event.target.value)}
            />
          </label>
          <label>
            {t("dual.meterAddress")}
            <input
              list="connected-addresses"
              value={meterAddress}
              onChange={(event) => setMeterAddress(event.target.value)}
            />
          </label>
          <label>
            {t("dual.sourceSchema")}
            <input value={sourceSchema} onChange={(event) => setSourceSchema(event.target.value)} />
          </label>
          <label>
            {t("dual.meterSchema")}
            <input value={meterSchema} onChange={(event) => setMeterSchema(event.target.value)} />
          </label>
          <label>
            {t("dual.startV")}
            <input value={startVoltage} onChange={(event) => setStartVoltage(event.target.value)} />
          </label>
          <label>
            {t("dual.stopV")}
            <input value={stopVoltage} onChange={(event) => setStopVoltage(event.target.value)} />
          </label>
          <label>
            {t("dual.stepV")}
            <input value={step} onChange={(event) => setStep(event.target.value)} />
          </label>
          <label>
            {t("dual.complianceA")}
            <input value={compliance} onChange={(event) => setCompliance(event.target.value)} />
          </label>
          <label>
            {t("dual.delayMs")}
            <input value={delayMs} onChange={(event) => setDelayMs(event.target.value)} />
          </label>
          <label>
            {t("dual.meterRange")}
            <input value={meterRange} onChange={(event) => setMeterRange(event.target.value)} />
          </label>
          <label>
            {t("dual.direction")}
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
          <Button onClick={handleAiPlan} disabled={busy}>{t("dual.aiPlan")}</Button>
          <Button onClick={handlePlan} disabled={busy}>{t("dual.plan")}</Button>
          <Button onClick={handleDryRun} disabled={busy}>{t("dual.dryRun")}</Button>
          <Button onClick={handleExecute} disabled={busy} variant="destructive">{t("dual.execute")}</Button>
          <Button onClick={handleExport} disabled={!run?.result} variant="outline">{t("dual.exportCsv")}</Button>
        </div>
        {error && <div className="sweep-error">{error}</div>}
      </section>

      <section className="dual-run panel">
        <h2>{t("dual.runState")}</h2>
        <div className="dual-summary">
          <span>{t("common.run")}: {run?.run_id ?? "-"}</span>
          <span>{t("common.status")}: {run?.status ?? "idle"}</span>
          <span>{t("common.points")}: {run?.validation?.estimated_points ?? run?.result?.summary.points ?? "-"}</span>
          <span>{t("common.mean")}: {formatNumber(run?.result?.summary.mean ?? null)}</span>
        </div>
        {run?.validation && (
          <div className={`validation-result ${run.validation.valid ? "pass" : "fail"}`}>
            <div className="validation-header">
              {run.validation.valid ? t("dual.validationPassed") : t("dual.validationBlocked")}
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
          <h3>{t("dual.commandPreview")}</h3>
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
            <h3>{t("dual.records")}</h3>
            <Button onClick={refreshRuns} disabled={busy} variant="outline" size="sm">
              {t("common.refresh")}
            </Button>
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
            {runs.length === 0 && <li className="dual-history-empty">{t("dual.noRecords")}</li>}
          </ul>
        </div>
      </section>

      <section className="dual-results panel">
        <h2>{t("dual.result")}</h2>
        <DualSweepChart run={run} />
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>{t("dual.sourceVoltage")}</th>
                <th>{t("dual.meterValue")}</th>
                <th>{t("common.timestamp")}</th>
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
                  <td colSpan={3}>{t("common.noData")}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
