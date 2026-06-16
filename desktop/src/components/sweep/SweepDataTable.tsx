import { useTranslation } from "react-i18next";
import { SweepPoint } from "../../types";

interface SweepDataTableProps {
  points: SweepPoint[];
}

const MAX_ROWS = 100;

export default function SweepDataTable({ points }: SweepDataTableProps) {
  const { t } = useTranslation();
  const totalRows = points.length;
  const displayPoints = points.slice(-MAX_ROWS);
  const hiddenCount = totalRows - displayPoints.length;

  return (
    <div className="sweep-data-table">
      <div className="table-header">
        <h3>{t("sweep.dataTable")}</h3>
        <span className="row-count">{t("sweep.rowsTotal", { count: totalRows })}</span>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>{t("sweep.voltage")}</th>
              <th>{t("sweep.current")}</th>
              <th>{t("common.timestamp")}</th>
            </tr>
          </thead>
          <tbody>
            {displayPoints.map((point, idx) => (
              <tr key={idx}>
                <td>{point.voltage.toFixed(3)}</td>
                <td>{point.current.toExponential(3)}</td>
                <td>{new Date(point.timestamp).toLocaleTimeString()}</td>
              </tr>
            ))}
            {hiddenCount > 0 && (
              <tr className="more-rows">
                <td colSpan={3}>{t("sweep.moreRows", { count: hiddenCount })}</td>
              </tr>
            )}
            {totalRows === 0 && (
              <tr className="no-data">
                <td colSpan={3}>{t("common.noData")}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
