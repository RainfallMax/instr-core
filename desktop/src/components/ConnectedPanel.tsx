import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ConnectedPanelProps } from "../types";
import { Button } from "./ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/Card";

export default function ConnectedPanel({
  connected,
  selected,
  onSelect,
  onBrowseSchema,
  onOpenTerminal,
  onDisconnect,
}: ConnectedPanelProps) {
  const { t } = useTranslation();
  const [disconnecting, setDisconnecting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const disconnect = async (address: string) => {
    if (!onDisconnect) return;
    setDisconnecting(address);
    setError(null);
    try {
      await onDisconnect(address);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : t("panels.disconnectFailed"),
      );
    } finally {
      setDisconnecting(null);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("panels.connected")}</CardTitle>
      </CardHeader>
      <CardContent>
      {error && <div className="visa-error">{error}</div>}
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
                <span className="no-schema-hint">{t("panels.noSchema")}</span>
              )}
            </label>
            {inst.schema_key && (
              <div className="instrument-actions">
                <Button
                  className="action-btn browse"
                  variant="outline"
                  size="sm"
                  onClick={() => onBrowseSchema?.(inst.schema_key!)}
                >
                  {t("panels.browseSchema")}
                </Button>
                <Button
                  className="action-btn terminal"
                  variant="outline"
                  size="sm"
                  onClick={() => onOpenTerminal?.(inst.address)}
                >
                  {t("panels.terminal")}
                </Button>
                <Button
                  className="action-btn disconnect"
                  variant="destructive"
                  size="sm"
                  disabled={disconnecting === inst.address}
                  onClick={() => disconnect(inst.address)}
                >
                  {disconnecting === inst.address
                    ? t("panels.disconnecting")
                    : t("panels.disconnect")}
                </Button>
              </div>
            )}
            {!inst.schema_key && onDisconnect && (
              <div className="instrument-actions">
                <Button
                  className="action-btn disconnect"
                  variant="destructive"
                  size="sm"
                  disabled={disconnecting === inst.address}
                  onClick={() => disconnect(inst.address)}
                >
                  {disconnecting === inst.address
                    ? t("panels.disconnecting")
                    : t("panels.disconnect")}
                </Button>
              </div>
            )}
          </li>
        ))}
      </ul>
      </CardContent>
    </Card>
  );
}
