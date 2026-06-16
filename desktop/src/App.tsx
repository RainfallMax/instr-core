import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { API_BASE, ConnectedInstrument, CommandDef } from "./types";
import SchemaListPanel from "./components/SchemaListPanel";
import VisaResourcePanel from "./components/VisaResourcePanel";
import ConnectedPanel from "./components/ConnectedPanel";
import ScpiTerminal from "./components/ScpiTerminal";
import SchemaBrowser from "./components/SchemaBrowser";
import CommandDetail from "./components/CommandDetail";
import IvSweepPanel from "./components/sweep/IvSweepPanel";
import DualKeithleyPanel from "./components/agent/DualKeithleyPanel";
import { Button } from "./components/ui/Button";
import "./App.css";

function App() {
  const { t, i18n } = useTranslation();
  const [connected, setConnected] = useState<ConnectedInstrument[]>([]);
  const [selectedInstrument, setSelectedInstrument] = useState<string>("");
  const [status, setStatus] = useState<string>(t("app.statusChecking"));
  const [selectedSchemaKey, setSelectedSchemaKey] = useState<string | null>(null);
  const [selectedCommand, setSelectedCommand] = useState<CommandDef | null>(null);
  const [activeView, setActiveView] = useState<"main" | "schema" | "sweep" | "dual">("main");

  // Health check on mount
  useEffect(() => {
    fetch(`${API_BASE}/health`)
      .then((r) => r.json())
      .then((data) => {
        setStatus(t("app.statusOk", {
          count: data.registry_count,
          pyvisa: String(data.pyvisa_available),
        }));
      })
      .catch(() => setStatus(t("app.statusUnreachable")));
  }, [t]);

  const changeLanguage = (language: string) => {
    i18n.changeLanguage(language);
    window.localStorage.setItem("instr-core-language", language);
  };

  const handleConnect = (inst: ConnectedInstrument) => {
    setConnected((prev) => [...prev, inst]);
  };

  const handleSelectSchema = (key: string) => {
    setSelectedSchemaKey(key);
    setActiveView("schema");
  };

  const handleBrowseSchema = (schemaKey: string) => {
    setSelectedSchemaKey(schemaKey);
    setActiveView("schema");
  };

  const handleOpenTerminal = (address: string) => {
    setSelectedInstrument(address);
    setActiveView("main");
  };

  const handleBackToMain = () => {
    setActiveView("main");
    setSelectedSchemaKey(null);
    setSelectedCommand(null);
  };

  const handleSelectCommand = (cmd: CommandDef) => {
    setSelectedCommand(cmd);
  };

  const handleCloseCommandDetail = () => {
    setSelectedCommand(null);
  };

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-left">
          <h1>instr-core</h1>
          {activeView === "schema" && (
            <Button variant="outline" size="sm" className="back-button" onClick={handleBackToMain}>
              {t("app.nav.back")}
            </Button>
          )}
        </div>
        <div className="header-right">
          <div className="view-toggle">
            <Button
              className={activeView === "main" ? "active" : ""}
              onClick={() => {
                setActiveView("main");
                setSelectedSchemaKey(null);
                setSelectedCommand(null);
              }}
            >
              {t("app.nav.main")}
            </Button>
            <Button
              className={activeView === "schema" ? "active" : ""}
              onClick={() => {
                if (selectedSchemaKey) {
                  setActiveView("schema");
                }
              }}
            >
              {t("app.nav.schemas")}
            </Button>
            <Button
              className={activeView === "sweep" ? "active" : ""}
              onClick={() => setActiveView("sweep")}
            >
              {t("app.nav.sweep")}
            </Button>
            <Button
              className={activeView === "dual" ? "active" : ""}
              onClick={() => setActiveView("dual")}
            >
              {t("app.nav.dual")}
            </Button>
          </div>
          <select
            className="language-select"
            aria-label={t("language.label")}
            value={i18n.language}
            onChange={(event) => changeLanguage(event.target.value)}
          >
            <option value="zh">{t("language.zh")}</option>
            <option value="en">{t("language.en")}</option>
          </select>
          <span className="status">{status}</span>
        </div>
      </header>

      <main className="app-main">
        {activeView === "main" ? (
          <>
            <SchemaListPanel onSelectSchema={handleSelectSchema} />
            <VisaResourcePanel onConnect={handleConnect} />
            <ConnectedPanel
              connected={connected}
              selected={selectedInstrument}
              onSelect={setSelectedInstrument}
              onBrowseSchema={handleBrowseSchema}
              onOpenTerminal={handleOpenTerminal}
            />
            <ScpiTerminal
              selectedInstrument={selectedInstrument}
              connected={connected}
              onSelectInstrument={setSelectedInstrument}
            />
          </>
        ) : activeView === "schema" ? (
          <div className="schema-browser-view">
            <SchemaBrowser
              schemaKey={selectedSchemaKey ?? undefined}
              onSelectCommand={handleSelectCommand}
            />
          </div>
        ) : activeView === "sweep" ? (
          <IvSweepPanel connected={connected} />
        ) : (
          <DualKeithleyPanel connected={connected} />
        )}
      </main>

      {selectedCommand && (
        <CommandDetail
          command={selectedCommand}
          onClose={handleCloseCommandDetail}
        />
      )}
    </div>
  );
}

export default App;
