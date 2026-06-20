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

export interface EmergencyStopResult {
  address: string;
  operation_id: string;
  safe: boolean;
  attempted_commands: string[];
  successful_command?: string;
  errors: string[];
}

export interface EmergencyStopResponse {
  all_safe: boolean;
  results: EmergencyStopResult[];
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
  onDisconnect?: (address: string) => Promise<void>;
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

// ---------------------------------------------------------------------------
// Dual Keithley Agent types
// ---------------------------------------------------------------------------

export interface InstrumentBinding {
  address: string;
  instrument_key: string;
}

export interface MeterConfig {
  function: "VOLT:DC";
  range: number;
}

export interface AgentValidationResult {
  valid: boolean;
  issues: string[];
  warnings: string[];
  suggestions: string[];
  commands: string[];
  estimated_points: number;
  requires_confirmation: boolean;
}

export interface DualKeithleyPlan {
  plan_id: string;
  experiment_type: "dual_keithley_sweep";
  mode: "dry_run" | "execute";
  goal: string;
  source: InstrumentBinding;
  meter: InstrumentBinding;
  source_config: SweepConfig;
  meter_config: MeterConfig;
  commands: Record<"source" | "meter", string[]>;
  requires_confirmation: boolean;
}

export interface DualSweepPoint {
  source_voltage: number;
  meter_value: number;
  timestamp: string;
}

export interface DualSweepSummary {
  points: number;
  min: number | null;
  max: number | null;
  mean: number | null;
}

export interface DualSweepResult {
  points: DualSweepPoint[];
  summary: DualSweepSummary;
}

export interface DualKeithleyRun {
  run_id: string;
  plan: DualKeithleyPlan;
  validation: AgentValidationResult | null;
  status: "planned" | "dry_run" | "running" | "completed" | "failed";
  error_message: string | null;
  result: DualSweepResult | null;
}

export interface DualKeithleyPlanResponse {
  run: DualKeithleyRun;
}

export interface AgentRunSummary {
  run_id: string;
  experiment_type: "iv_sweep" | "dual_keithley_sweep";
  status: string;
  goal: string;
  has_validation: boolean;
  has_result: boolean;
}

export interface AgentRunsResponse {
  runs: AgentRunSummary[];
}
