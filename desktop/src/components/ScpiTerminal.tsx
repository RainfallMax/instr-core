import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  API_BASE,
  CommandResponse,
  ScpiTerminalProps,
  ValidateResponse,
} from "../types";
import { Button } from "./ui/Button";

export default function ScpiTerminal({
  selectedInstrument,
  connected,
  onSelectInstrument,
}: ScpiTerminalProps) {
  const { t } = useTranslation();
  const [command, setCommand] = useState<string>("");
  const [commandResult, setCommandResult] = useState<CommandResponse | null>(null);
  const [validationResult, setValidationResult] = useState<ValidateResponse | null>(null);
  const [isValidating, setIsValidating] = useState<boolean>(false);

  const validationTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Get selected instrument's schema_key
  const selectedSchemaKey = connected.find(
    (inst) => inst.address === selectedInstrument
  )?.schema_key;

  // Debounced validation
  const validateCommand = (cmd: string) => {
    // Clear existing timeout
    if (validationTimeoutRef.current) {
      clearTimeout(validationTimeoutRef.current);
    }

    // Reset validation if no command or no schema_key
    if (!cmd.trim() || !selectedSchemaKey) {
      setValidationResult(null);
      return;
    }

    setIsValidating(true);

    validationTimeoutRef.current = setTimeout(async () => {
      try {
        const res = await fetch(`${API_BASE}/validate/command`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            instrument: selectedSchemaKey,
            command: cmd.trim(),
          }),
        });

        if (!res.ok) {
          // Gracefully handle non-OK responses
          setValidationResult(null);
          return;
        }

        const data: ValidateResponse = await res.json();
        setValidationResult(data);
      } catch (err) {
        // Gracefully handle network errors
        setValidationResult(null);
      } finally {
        setIsValidating(false);
      }
    }, 300);
  };

  // Handle command input change
  const handleCommandChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newCommand = e.target.value;
    setCommand(newCommand);
    validateCommand(newCommand);
  };

  // Send SCPI command
  const sendCommand = async () => {
    if (!selectedInstrument || !command) return;
    const res = await fetch(`${API_BASE}/visa/command`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        address: selectedInstrument,
        command,
        validate: true,
      }),
    });
    const data = await res.json();
    setCommandResult(data);
  };

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (validationTimeoutRef.current) {
        clearTimeout(validationTimeoutRef.current);
      }
    };
  }, []);

  return (
    <section className="panel terminal">
      <h2>{t("terminal.title")}</h2>
      <div className="terminal-input">
        <select
          value={selectedInstrument}
          onChange={(e) => {
            onSelectInstrument?.(e.target.value);
            setCommand("");
            setValidationResult(null);
          }}
        >
          <option value="">{t("terminal.select")}</option>
          {connected.map((inst) => (
            <option key={inst.address} value={inst.address}>
              {inst.manufacturer} {inst.model} ({inst.address})
            </option>
          ))}
        </select>
        <input
          type="text"
          value={command}
          onChange={handleCommandChange}
          onKeyDown={(e) => e.key === "Enter" && sendCommand()}
          placeholder={t("terminal.placeholder")}
        />
        <Button
          onClick={sendCommand}
          disabled={!selectedInstrument || !command}
          className={validationResult && !validationResult.valid ? "send-blocked" : ""}
        >
          {t("terminal.send")}
        </Button>
      </div>

      {/* Validation Result */}
      {validationResult && selectedSchemaKey && (
        <div className={`validation-result ${validationResult.valid ? "pass" : "fail"}`}>
          <div className="validation-header">
            {validationResult.valid ? `✓ ${t("terminal.valid")}` : `✗ ${t("terminal.blocked")}`}
          </div>
          {validationResult.issues.length > 0 && (
            <div className="validation-issues">
              <strong>{t("terminal.issues")}</strong>
              <ul>
                {validationResult.issues.map((issue, i) => (
                  <li key={i}>{issue}</li>
                ))}
              </ul>
            </div>
          )}
          {validationResult.suggestions.length > 0 && (
            <div className="validation-suggestions">
              <strong>{t("terminal.suggestions")}</strong>
              <ul>
                {validationResult.suggestions.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {isValidating && <div className="validation-loading">{t("terminal.validating")}</div>}

      {commandResult && (
        <div className="terminal-output">
          <div className="output-line">
            <span className="prompt">{commandResult.address}</span>
            <code className="cmd">{commandResult.command}</code>
          </div>
          {commandResult.response && (
            <div className="output-line response">
              <code>{commandResult.response}</code>
            </div>
          )}
          {commandResult.error && (
            <div className="output-line error">{commandResult.error}</div>
          )}
          {commandResult.validation_issues.length > 0 && (
            <div className="validation-warnings">
              <strong>{t("terminal.validationIssues")}</strong>
              <ul>
                {commandResult.validation_issues.map((issue, i) => (
                  <li key={i}>{issue}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
