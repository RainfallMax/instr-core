import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import * as echarts from "echarts/core";
import {
  DatasetComponent,
  GraphicComponent,
  GridComponent,
  TooltipComponent,
} from "echarts/components";
import { LineChart } from "echarts/charts";
import { CanvasRenderer } from "echarts/renderers";
import { SweepPoint } from "../../types";

echarts.use([
  DatasetComponent,
  GraphicComponent,
  GridComponent,
  TooltipComponent,
  LineChart,
  CanvasRenderer,
]);

interface SweepChartProps {
  points: SweepPoint[];
  direction?: string;
}

export default function SweepChart({ points }: SweepChartProps) {
  const { t } = useTranslation();
  const chartRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!chartRef.current) return;
    const chart = echarts.init(chartRef.current, "dark");
    chart.setOption({
      backgroundColor: "transparent",
      grid: { top: 28, right: 28, bottom: 48, left: 72 },
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "value",
        name: t("sweep.voltage"),
        nameLocation: "middle",
        nameGap: 30,
        axisLine: { lineStyle: { color: "#a1a1aa" } },
        splitLine: { lineStyle: { color: "#262626" } },
      },
      yAxis: {
        type: "value",
        name: t("sweep.current"),
        nameLocation: "middle",
        nameGap: 48,
        axisLine: { lineStyle: { color: "#a1a1aa" } },
        splitLine: { lineStyle: { color: "#262626" } },
      },
      series: [
        {
          type: "line",
          symbol: "circle",
          symbolSize: 6,
          data: points.map((point) => [point.voltage, point.current]),
          lineStyle: { width: 2, color: "#fafafa" },
          itemStyle: { color: "#fafafa" },
        },
      ],
      graphic:
        points.length === 0
          ? {
              type: "text",
              left: "center",
              top: "middle",
              style: { text: t("common.noData"), fill: "#71717a", fontSize: 14 },
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

  return <div className="sweep-chart echarts-panel" ref={chartRef} />;
}
