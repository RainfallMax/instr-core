import { useEffect, useState } from "react";
import { API_BASE, ConnectedInstrument, CommandDef } from "./types";
import SchemaListPanel from "./components/SchemaListPanel";
import VisaResourcePanel from "./components/VisaResourcePanel";
import ConnectedPanel from "./components/ConnectedPanel";
import ScpiTerminal from "./components/ScpiTerminal";
import SchemaBrowser from "./components/SchemaBrowser";
import CommandDetail from "./components/CommandDetail";
import IvSweepPanel from "./components/sweep/IvSweepPanel";
import "./App.css";

function App() {
  const [connected, setConnected] = useState<ConnectedInstrument[]>([]);
  const [selectedInstrument, setSelectedInstrument] = useState<string>("");
  const [status, setStatus] = useState<string>("checking...");
  const [selectedSchemaKey, setSelectedSchemaKey] = useState<string | null>(null);
  const [selectedCommand, setSelectedCommand] = useState<CommandDef | null>(null);
  const [activeView, setActiveView] = useState<"main" | "schema" | "sweep">("main");

  // Health check on mount
  useEffect(() => {
    fetch(`${API_BASE}/health`)
      .then((r) => r.json())
      .then((data) => {
        setStatus(`API ok · ${data.registry_count} schemas · pyvisa: ${data.pyvisa_available}`);
      })
      .catch(() => setStatus("API unreachable — is the Python backend running?"));
  }, []);

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
            <button className="back-button" onClick={handleBackToMain}>
              ← Back to main
            </button>
          )}
        </div>
        <div className="header-right">
          <div className="view-toggle">
            <button
              className={activeView === "main" ? "active" : ""}
              onClick={() => {
                setActiveView("main");
                setSelectedSchemaKey(null);
                setSelectedCommand(null);
              }}
            >
              Main
            </button>
            <button
              className={activeView === "schema" ? "active" : ""}
              onClick={() => {
                if (selectedSchemaKey) {
                  setActiveView("schema");
                }
              }}
            >
              Browse Schemas
            </button>
            <button
              className={activeView === "sweep" ? "active" : ""}
              onClick={() => setActiveView("sweep")}
            >
              IV Sweep
            </button>
          </div>
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
        ) : (
          <IvSweepPanel connected={connected} />
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
