import React from "react";
import { SweepConfig } from "../../types";

interface SweepConfigFormProps {
  config: SweepConfig;
  onChange: (config: SweepConfig) => void;
  disabled: boolean;
  onStart: () => void;
  onStop: () => void;
  status: "idle" | "running" | "completed" | "aborted" | "error";
  canStart: boolean;
  progress?: { current: number; total: number };
}

export default function SweepConfigForm({
  config,
  onChange,
  disabled,
  onStart,
  onStop,
  status,
  canStart,
  progress,
}: SweepConfigFormProps) {
  const handleChange = (field: keyof SweepConfig, rawValue: string | number) => {
    let value: string | number = rawValue;
    // Guard against NaN from empty/invalid numeric inputs
    if (typeof rawValue === "number" && Number.isNaN(rawValue)) {
      const fallback: Partial<Record<keyof SweepConfig, number | string>> = {
        start_voltage: 0,
        stop_voltage: 10,
        step: 0.5,
        compliance: 0.01,
        delay_ms: 10,
        direction: "UP",
      };
      value = fallback[field] ?? 0;
    }
    onChange({ ...config, [field]: value });
  };

  const isRunning = status === "running";
  const canStartSweep = canStart && !isRunning && (status === "idle" || status === "completed" || status === "aborted" || status === "error");

  return (
    <div className="sweep-config-form">
      <h3>Sweep Configuration</h3>
      <div className="form-fields">
        <label>
          <span>Start Voltage (V)</span>
          <input
            type="number"
            step="0.1"
            value={config.start_voltage}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => handleChange("start_voltage", parseFloat(e.target.value))}
            disabled={disabled}
          />
        </label>
        <label>
          <span>Stop Voltage (V)</span>
          <input
            type="number"
            step="0.1"
            value={config.stop_voltage}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => handleChange("stop_voltage", parseFloat(e.target.value))}
            disabled={disabled}
          />
        </label>
        <label>
          <span>Step (V)</span>
          <input
            type="number"
            step="0.01"
            value={config.step}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => handleChange("step", parseFloat(e.target.value))}
            disabled={disabled}
          />
        </label>
        <label>
          <span>Compliance (A)</span>
          <input
            type="number"
            step="0.001"
            value={config.compliance}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => handleChange("compliance", parseFloat(e.target.value))}
            disabled={disabled}
          />
        </label>
        <label>
          <span>Delay (ms)</span>
          <input
            type="number"
            step="1"
            value={config.delay_ms}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => handleChange("delay_ms", parseInt(e.target.value))}
            disabled={disabled}
          />
        </label>
        <label>
          <span>Direction</span>
          <select
            value={config.direction}
            onChange={(e: React.ChangeEvent<HTMLSelectElement>) => handleChange("direction", e.target.value)}
            disabled={disabled}
          >
            <option value="UP">UP</option>
            <option value="DOWN">DOWN</option>
            <option value="BOTH">BOTH</option>
          </select>
        </label>
      </div>

      <div className="form-actions">
        <button
          className="start-button"
          onClick={onStart}
          disabled={!canStartSweep}
        >
          Start Sweep
        </button>
        <button
          className="stop-button"
          onClick={onStop}
          disabled={!isRunning}
        >
          Stop
        </button>
      </div>

      {isRunning && progress && (
        <div className="sweep-progress">
          <span>Scanning: {progress.current}/{progress.total} points</span>
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{
                width: `${progress.total > 0 ? (progress.current / progress.total) * 100 : 0}%`,
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
}