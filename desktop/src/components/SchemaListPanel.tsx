import { useState } from "react";
import { useTranslation } from "react-i18next";
import { API_BASE, InstrumentMeta, SchemaListPanelProps } from "../types";
import { Button } from "./ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/Card";

export default function SchemaListPanel({ onSelectSchema }: SchemaListPanelProps) {
  const { t } = useTranslation();
  const [instruments, setInstruments] = useState<InstrumentMeta[]>([]);

  const loadInstruments = async () => {
    const res = await fetch(`${API_BASE}/instruments`);
    const data = await res.json();
    setInstruments(data);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("panels.schemas")}</CardTitle>
      </CardHeader>
      <CardContent>
      <Button onClick={loadInstruments}>{t("panels.loadRegistry")}</Button>
      <ul className="list">
        {instruments.map((inst) => (
          <li
            key={inst.key}
            className="list-item"
            onClick={() => onSelectSchema?.(inst.key)}
            style={{ cursor: onSelectSchema ? "pointer" : "default" }}
          >
            <strong>
              {inst.manufacturer} {inst.model}
            </strong>
            <span className="key">{inst.key}</span>
            {inst.description && <span className="desc">{inst.description}</span>}
          </li>
        ))}
      </ul>
      </CardContent>
    </Card>
  );
}
