import { SweepPoint } from "../../types";

interface SweepChartProps {
  points: SweepPoint[];
  direction?: string;
}

const VIEWBOX_WIDTH = 600;
const VIEWBOX_HEIGHT = 400;
const MARGIN = { top: 20, right: 30, bottom: 50, left: 60 };
const CHART_WIDTH = VIEWBOX_WIDTH - MARGIN.left - MARGIN.right;
const CHART_HEIGHT = VIEWBOX_HEIGHT - MARGIN.top - MARGIN.bottom;

function getMinMax(values: number[]): [number, number] {
  if (values.length === 0) return [0, 1];
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (min === max) return [min - 1, max + 1];
  const padding = (max - min) * 0.1;
  return [min - padding, max + padding];
}

function scale(value: number, min: number, max: number, range: number): number {
  return ((value - min) / (max - min)) * range;
}

function formatAxisLabel(value: number): string {
  if (Math.abs(value) >= 1000) return value.toExponential(1);
  if (Math.abs(value) >= 1) return value.toFixed(1);
  if (Math.abs(value) >= 0.01) return value.toFixed(2);
  return value.toExponential(1);
}

export default function SweepChart({ points, direction }: SweepChartProps) {
  if (points.length === 0) {
    return (
      <div className="sweep-chart empty">
        <svg viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`}>
          <text
            x={VIEWBOX_WIDTH / 2}
            y={VIEWBOX_HEIGHT / 2}
            textAnchor="middle"
            fill="#6c7086"
            fontSize="14"
          >
            No data
          </text>
        </svg>
      </div>
    );
  }

  const voltages = points.map((p) => p.voltage);
  const currents = points.map((p) => p.current);
  const [vMin, vMax] = getMinMax(voltages);
  const [iMin, iMax] = getMinMax(currents);

  const xScale = (v: number) =>
    MARGIN.left + scale(v, vMin, vMax, CHART_WIDTH);
  const yScale = (i: number) =>
    MARGIN.top + CHART_HEIGHT - scale(i, iMin, iMax, CHART_HEIGHT);

  // Grid lines
  const xTicks = 5;
  const yTicks = 5;
  const xGridLines = Array.from({ length: xTicks + 1 }, (_, i) => {
    const v = vMin + (vMax - vMin) * (i / xTicks);
    const x = xScale(v);
    return (
      <g key={`xgrid-${i}`}>
        <line
          x1={x}
          y1={MARGIN.top}
          x2={x}
          y2={MARGIN.top + CHART_HEIGHT}
          stroke="#313244"
          strokeWidth="1"
          strokeDasharray="4,4"
        />
        <text
          x={x}
          y={MARGIN.top + CHART_HEIGHT + 18}
          textAnchor="middle"
          fill="#a6adc8"
          fontSize="10"
          fontFamily="SF Mono, Monaco, monospace"
        >
          {formatAxisLabel(v)}
        </text>
      </g>
    );
  });

  const yGridLines = Array.from({ length: yTicks + 1 }, (_, i) => {
    const c = iMin + (iMax - iMin) * (i / yTicks);
    const y = yScale(c);
    return (
      <g key={`ygrid-${i}`}>
        <line
          x1={MARGIN.left}
          y1={y}
          x2={MARGIN.left + CHART_WIDTH}
          y2={y}
          stroke="#313244"
          strokeWidth="1"
          strokeDasharray="4,4"
        />
        <text
          x={MARGIN.left - 8}
          y={y + 4}
          textAnchor="end"
          fill="#a6adc8"
          fontSize="10"
          fontFamily="SF Mono, Monaco, monospace"
        >
          {formatAxisLabel(c)}
        </text>
      </g>
    );
  });

  // Split points into segments by direction for BOTH mode
  const segments: { points: SweepPoint[]; color: string }[] = [];
  if (direction === "BOTH" && points.length > 1) {
    let currentSegment: SweepPoint[] = [points[0]];
    let currentDirection: "up" | "down" =
      points[1].voltage >= points[0].voltage ? "up" : "down";

    for (let i = 1; i < points.length; i++) {
      const newDir = points[i].voltage >= points[i - 1].voltage ? "up" : "down";
      if (newDir !== currentDirection) {
        segments.push({
          points: [...currentSegment],
          color: currentDirection === "up" ? "#89b4fa" : "#f9e2af",
        });
        currentSegment = [points[i - 1], points[i]];
        currentDirection = newDir;
      } else {
        currentSegment.push(points[i]);
      }
    }
    segments.push({
      points: currentSegment,
      color: currentDirection === "up" ? "#89b4fa" : "#f9e2af",
    });
  } else {
    segments.push({ points, color: "#89b4fa" });
  }

  const pathElements = segments.map((seg, idx) => {
    const d = seg.points
      .map((p, i) => `${i === 0 ? "M" : "L"} ${xScale(p.voltage)} ${yScale(p.current)}`)
      .join(" ");
    return (
      <path
        key={`path-${idx}`}
        d={d}
        fill="none"
        stroke={seg.color}
        strokeWidth="2"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    );
  });

  const circles = points.map((p, i) => (
    <circle
      key={i}
      cx={xScale(p.voltage)}
      cy={yScale(p.current)}
      r="3"
      fill="#89b4fa"
      stroke="#181825"
      strokeWidth="1"
    />
  ));

  return (
    <div className="sweep-chart">
      <svg viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`}>
        {/* Grid */}
        {xGridLines}
        {yGridLines}

        {/* Axes */}
        <line
          x1={MARGIN.left}
          y1={MARGIN.top + CHART_HEIGHT}
          x2={MARGIN.left + CHART_WIDTH}
          y2={MARGIN.top + CHART_HEIGHT}
          stroke="#cdd6f4"
          strokeWidth="1.5"
        />
        <line
          x1={MARGIN.left}
          y1={MARGIN.top}
          x2={MARGIN.left}
          y2={MARGIN.top + CHART_HEIGHT}
          stroke="#cdd6f4"
          strokeWidth="1.5"
        />

        {/* Axis labels */}
        <text
          x={MARGIN.left + CHART_WIDTH / 2}
          y={VIEWBOX_HEIGHT - 8}
          textAnchor="middle"
          fill="#cdd6f4"
          fontSize="12"
          fontWeight="600"
        >
          Voltage (V)
        </text>
        <text
          x={15}
          y={MARGIN.top + CHART_HEIGHT / 2}
          textAnchor="middle"
          fill="#cdd6f4"
          fontSize="12"
          fontWeight="600"
          transform={`rotate(-90, 15, ${MARGIN.top + CHART_HEIGHT / 2})`}
        >
          Current (A)
        </text>

        {/* Data paths */}
        {pathElements}

        {/* Data points */}
        {circles}
      </svg>
    </div>
  );
}
