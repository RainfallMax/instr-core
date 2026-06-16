import { SweepHistoryItem } from "../../types";

interface SweepHistoryProps {
  sessions: SweepHistoryItem[];
  onSelect: (session_id: string) => void;
}

function formatDate(isoString: string): string {
  const d = new Date(isoString);
  return d.toLocaleString();
}

function getStatusClass(status: string): string {
  switch (status) {
    case "completed":
      return "status-completed";
    case "running":
      return "status-running";
    case "error":
      return "status-error";
    case "aborted":
      return "status-aborted";
    default:
      return "status-idle";
  }
}

export default function SweepHistory({ sessions, onSelect }: SweepHistoryProps) {
  if (sessions.length === 0) {
    return (
      <div className="sweep-history empty">
        <h3>Sweep History</h3>
        <p className="empty-message">No sweep history</p>
      </div>
    );
  }

  return (
    <div className="sweep-history">
      <h3>Sweep History</h3>
      <ul className="history-list">
        {sessions.map((session) => (
          <li
            key={session.session_id}
            className="history-item"
            onClick={() => onSelect(session.session_id)}
          >
            <div className="history-row">
              <span className="history-instrument">{session.instrument_key}</span>
              <span className={`history-status ${getStatusClass(session.status)}`}>
                {session.status}
              </span>
            </div>
            <div className="history-meta">
              <span>{session.points_count} points</span>
              <span className="history-time">{formatDate(session.created_at)}</span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
