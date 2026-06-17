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

  const navItems: { key: typeof activeView; label: string; description: string }[] = [
    {
      key: "main",
      label: t("app.nav.main"),
      description: t("app.nav.mainDescription"),
    },
    {
      key: "dual",
      label: t("app.nav.dual"),
      description: t("app.nav.dualDescription"),
    },
    {
      key: "sweep",
      label: t("app.nav.sweep"),
      description: t("app.nav.sweepDescription"),
    },
    {
      key: "schema",
      label: t("app.nav.schemas"),
      description: t("app.nav.schemasDescription"),
    },
  ];

  const activeNavItem = navItems.find((item) => item.key === activeView) ?? navItems[0];

  const handleSelectView = (view: typeof activeView) => {
    if (view === "schema" && !selectedSchemaKey) {
      return;
    }
    setActiveView(view);
    if (view === "main") {
      setSelectedSchemaKey(null);
      setSelectedCommand(null);
    }
  };

  return (
    <div className="app">
      <aside className="app-sidebar">
        <div className="brand-block">
          <div className="brand-mark">ic</div>
          <div>
            <h1>instr-core</h1>
            <p>{t("app.shellTagline")}</p>
          </div>
        </div>
        <nav className="sidebar-nav" aria-label={t("app.navLabel")}>
          {navItems.map((item) => (
            <button
              key={item.key}
              className={activeView === item.key ? "active" : ""}
              disabled={item.key === "schema" && !selectedSchemaKey}
              onClick={() => handleSelectView(item.key)}
            >
              <span>{item.label}</span>
              <small>{item.description}</small>
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="sidebar-stat">
            <span>{t("app.connected")}</span>
            <strong>{connected.length}</strong>
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
        </div>
      </aside>

      <section className="app-workspace">
        <header className="workspace-header">
          <div>
            <p className="workspace-kicker">{t("app.workspace")}</p>
            <h2>{activeNavItem.label}</h2>
            <span>{activeNavItem.description}</span>
          </div>
          <div className="workspace-actions">
            {activeView === "schema" && (
              <Button variant="outline" size="sm" className="back-button" onClick={handleBackToMain}>
                {t("app.nav.back")}
              </Button>
            )}
            <span className="status">{status}</span>
          </div>
        </header>

        <main className="app-main">
          {activeView === "main" ? (
            <div className="main-workbench">
              <section className="workbench-column">
                <SchemaListPanel onSelectSchema={handleSelectSchema} />
                <VisaResourcePanel onConnect={handleConnect} />
              </section>
              <section className="workbench-column">
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
              </section>
            </div>
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
      </section>

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
