/** Shared TypeScript types for the instr-core desktop app.
 *
 * All components import from here to stay consistent.
 */

export const API_BASE = "http://localhost:8765";

// ---------------------------------------------------------------------------
// API response types
// ---------------------------------------------------------------------------

export interface InstrumentMeta {
  key: string;
  manufacturer: string;
  model: string;
  description?: string;
}

export interface ConnectedInstrument {
  address: string;
  manufacturer?: string;
  model?: string;
  serial?: string;
  idn?: string;
  schema_key?: string;
}

export interface CommandResponse {
  address: string;
  command: string;
  response?: string;
  error?: string;
  validated: boolean;
  validation_issues: string[];
  validation_suggestions: string[];
}

export interface ValidateResponse {
  instrument?: string;
  address?: string;
  command: string;
  argument?: string;
  valid: boolean;
  issues: string[];
  suggestions: string[];
}

// ---------------------------------------------------------------------------
// Schema types (mirror of Python Pydantic models)
// ---------------------------------------------------------------------------

export interface LimitDef {
  max: number;
  unit: string;
}

export interface GlobalLimits {
  voltage?: LimitDef;
  current?: LimitDef;
  power?: LimitDef;
  frequency?: LimitDef;
}

export interface ParameterDef {
  name: string;
  type: string;
  allowed_values?: string[];
}

export interface Range {
  min: number;
  max: number;
}

export interface SequenceRule {
  before?: string;
  after?: string;
  require_state_keys_present?: string[];
  expect_state?: Record<string, string>;
  message: string;
}

export interface Safety {
  compliance_required?: boolean;
  compliance_parameter?: string;
  sequence?: SequenceRule[];
}

export interface CommandDef {
  command: string;
  description?: string;
  parameters?: ParameterDef[];
  range?: Range;
  requires?: Record<string, string>;
  forbidden_when?: Record<string, string>;
  safety?: Safety;
  sets_state?: Record<string, string>;
  tags?: string[];
}

export interface InstrumentInfo {
  manufacturer: string;
  model: string;
  series?: string;
  category?: string;
  description?: string;
  firmware_version?: string;
  doc_source?: string;
}

export interface InstrumentSchema {
  version?: string;
  instrument: InstrumentInfo;
  global_limits: GlobalLimits;
  commands: CommandDef[];
}

export interface InstrumentDetail {
  key: string;
  schema: InstrumentSchema;
}

// ---------------------------------------------------------------------------
// Component prop types
// ---------------------------------------------------------------------------

export interface SchemaListPanelProps {
  onSelectSchema?: (key: string) => void;
}

export interface VisaResourcePanelProps {
  onConnect: (inst: ConnectedInstrument) => void;
}

export interface ConnectedPanelProps {
  connected: ConnectedInstrument[];
  selected: string;
  onSelect: (address: string) => void;
  onBrowseSchema?: (schemaKey: string) => void;
  onOpenTerminal?: (address: string) => void;
}

export interface ScpiTerminalProps {
  selectedInstrument: string;
  connected: ConnectedInstrument[];
  onSelectInstrument?: (address: string) => void;
}

export interface SchemaBrowserProps {
  schemaKey?: string;
  onSelectCommand?: (cmd: CommandDef) => void;
}

export interface CommandDetailProps {
  command: CommandDef;
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// IV Sweep types
// ---------------------------------------------------------------------------

export interface SweepConfig {
  start_voltage: number;
  stop_voltage: number;
  step: number;
  compliance: number;
  delay_ms: number;
  direction: "UP" | "DOWN" | "BOTH";
}

export interface SweepPoint {
  voltage: number;
  current: number;
  timestamp: string;
}

export interface SweepStartRequest {
  instrument_key: string;
  address: string;
  config: SweepConfig;
}

export interface SweepStartResponse {
  session_id: string;
  status: string;
  total_points: number;
}

export interface SweepStatusResponse {
  session_id: string;
  status: string;
  progress: { current: number; total: number };
  new_points: SweepPoint[];
  error_message: string | null;
}

export interface SweepHistoryItem {
  session_id: string;
  instrument_key: string;
  status: string;
  points_count: number;
  created_at: string;
  completed_at: string | null;
}
