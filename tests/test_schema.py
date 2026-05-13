"""Tests for schema parsing and validation logic."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from instr_core.schema import InstrumentSchema
from instr_core.server import SequenceStep, create_server
from instr_core.validator import Registry, validate_command


FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "registry"


SAMPLE_YAML = """
instrument:
  manufacturer: Keithley
  model: "2600"
  series: "2600A"
  description: "Series 2600A System SourceMeter Instruments"
  firmware_version: "3.x"
  doc_source: "Keithley 2600A Reference Manual"

global_limits:
  voltage: {max: 40.0, unit: "V"}
  current: {max: 3.0, unit: "A"}
  power: {max: 200.0, unit: "W"}

commands:
  - command: ":SOUR:FUNC"
    description: "Set the source function"
    parameters:
      - name: "function"
        type: "string"
        allowed_values: ["VOLT", "CURR"]
    requires:
      output: OFF

  - command: ":SOUR:VOLT"
    description: "Set the source voltage level"
    parameters:
      - name: "voltage"
        type: "float"
    range:
      min: -40.0
      max: 40.0
    requires:
      source_mode: VOLT
    forbidden_when:
      output: ON
    safety:
      compliance_required: true
      compliance_parameter: ":SENS:CURR:PROT"

  - command: ":OUTP"
    description: "Turn the output ON or OFF"
    parameters:
      - name: "state"
        type: "string"
        allowed_values: ["ON", "OFF"]
    safety:
      sequence:
        - before: ":OUTP ON"
          require_state_keys_present: [":SENS:CURR:PROT", ":SENS:VOLT:PROT"]
          message: "Compliance must be configured before enabling output"
"""


def test_parse_instrument_info() -> None:
    schema = InstrumentSchema.model_validate(yaml.safe_load(SAMPLE_YAML))
    assert schema.instrument.manufacturer == "Keithley"
    assert schema.instrument.model == "2600"
    assert schema.instrument.series == "2600A"


def test_parse_global_limits() -> None:
    schema = InstrumentSchema.model_validate(yaml.safe_load(SAMPLE_YAML))
    limits = schema.global_limits
    assert limits.voltage.max == 40.0
    assert limits.current.max == 3.0
    assert limits.power.max == 200.0
    assert limits.voltage.unit == "V"


def test_parse_commands() -> None:
    schema = InstrumentSchema.model_validate(yaml.safe_load(SAMPLE_YAML))
    assert len(schema.commands) == 3


def test_parse_command_requires() -> None:
    schema = InstrumentSchema.model_validate(yaml.safe_load(SAMPLE_YAML))
    sour_func = schema.commands[0]
    assert sour_func.command == ":SOUR:FUNC"
    assert sour_func.requires.get("output") == "OFF"


def test_parse_command_range() -> None:
    schema = InstrumentSchema.model_validate(yaml.safe_load(SAMPLE_YAML))
    sour_volt = schema.commands[1]
    assert sour_volt.range is not None
    assert sour_volt.range.min == -40.0
    assert sour_volt.range.max == 40.0


def test_parse_command_forbidden_when() -> None:
    schema = InstrumentSchema.model_validate(yaml.safe_load(SAMPLE_YAML))
    sour_volt = schema.commands[1]
    assert sour_volt.forbidden_when.get("output") == "ON"


def test_parse_safety() -> None:
    schema = InstrumentSchema.model_validate(yaml.safe_load(SAMPLE_YAML))
    sour_volt = schema.commands[1]
    assert sour_volt.safety is not None
    assert sour_volt.safety.compliance_required is True
    assert sour_volt.safety.compliance_parameter == ":SENS:CURR:PROT"


def test_parse_safety_sequence() -> None:
    schema = InstrumentSchema.model_validate(yaml.safe_load(SAMPLE_YAML))
    outp = schema.commands[2]
    assert outp.safety is not None
    assert len(outp.safety.sequence) == 1
    assert outp.safety.sequence[0].before == ":OUTP ON"
    assert outp.safety.sequence[0].require_state_keys_present == [
        ":SENS:CURR:PROT",
        ":SENS:VOLT:PROT",
    ]


def test_parse_allowed_values() -> None:
    schema = InstrumentSchema.model_validate(yaml.safe_load(SAMPLE_YAML))
    param = schema.commands[0].parameters[0]
    assert param.allowed_values == ["VOLT", "CURR"]


def test_parse_real_yaml_file() -> None:
    path = FIXTURES_ROOT / "keithley" / "smu" / "2600.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    schema = InstrumentSchema.model_validate(data)
    assert schema.instrument.manufacturer == "Keithley"
    assert schema.instrument.model == "2600"
    assert len(schema.commands) > 0


def test_parse_full_file_global_limits() -> None:
    path = FIXTURES_ROOT / "keithley" / "smu" / "2600.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    schema = InstrumentSchema.model_validate(data)
    assert schema.global_limits.voltage.max == 40.0
    assert schema.global_limits.current.max == 3.0


class TestValidator:
    @pytest.fixture(scope="class")
    def schema(self) -> InstrumentSchema:
        path = FIXTURES_ROOT / "keithley" / "smu" / "2600.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return InstrumentSchema.model_validate(data)

    def test_validate_unknown_command(self, schema: InstrumentSchema) -> None:
        result = validate_command(schema, ":FAKE:CMD", None, {})
        assert not result.valid
        assert "Unknown command" in result.issues[0]

    def test_validate_requires_missing(self, schema: InstrumentSchema) -> None:
        result = validate_command(schema, ":SOUR:FUNC", "VOLT", {})
        assert not result.valid
        assert any("Requirement not met" in i for i in result.issues)

    def test_validate_requires_met(self, schema: InstrumentSchema) -> None:
        result = validate_command(schema, ":SOUR:FUNC", "VOLT", {"output": "OFF"})
        assert result.valid, f"Expected valid, got: {result.issues}"

    def test_validate_forbidden_when(self, schema: InstrumentSchema) -> None:
        result = validate_command(
            schema, ":SOUR:VOLT", "5", {"output": "ON", "source_mode": "VOLT"}
        )
        assert not result.valid
        assert any("Forbidden" in i for i in result.issues)

    def test_validate_range_ok(self, schema: InstrumentSchema) -> None:
        state = {"source_mode": "VOLT", ":SENS:CURR:PROT": "0.01"}
        result = validate_command(schema, ":SOUR:VOLT", "10", state)
        assert result.valid, f"Expected valid, got: {result.issues}"

    def test_validate_range_fail(self, schema: InstrumentSchema) -> None:
        state = {"source_mode": "VOLT"}
        result = validate_command(schema, ":SOUR:VOLT", "50", state)
        assert not result.valid
        assert any("out of range" in i for i in result.issues)

    def test_validate_global_limit(self, schema: InstrumentSchema) -> None:
        state = {"source_mode": "VOLT"}
        result = validate_command(schema, ":SOUR:VOLT", "50", state)
        assert not result.valid

    def test_validate_allowed_values(self, schema: InstrumentSchema) -> None:
        state = {"output": "OFF"}
        result = validate_command(schema, ":SOUR:FUNC", "INVALID", state)
        assert not result.valid
        assert any("Invalid value" in i for i in result.issues)

    def test_validate_sequence_rule_compliance_missing(self, schema: InstrumentSchema) -> None:
        result = validate_command(schema, ":OUTP", "ON", {})
        assert not result.valid
        assert any(
            "Sequence safety" in i and "Compliance must be configured" in i
            for i in result.issues
        )

    def test_validate_sequence_rule_compliance_present(self, schema: InstrumentSchema) -> None:
        state = {":SENS:CURR:PROT": "0.01"}
        result = validate_command(schema, ":OUTP", "ON", state)
        assert result.valid, f"Expected valid, got: {result.issues}"

    def test_validate_sequence_rule_does_not_apply_to_off(self, schema: InstrumentSchema) -> None:
        # The :OUTP ON before rule should not trigger when argument is OFF.
        result = validate_command(schema, ":OUTP", "OFF", {})
        assert result.valid, f"Expected valid, got: {result.issues}"

    def test_validate_sequence_rule_after_fail(self, schema: InstrumentSchema) -> None:
        from instr_core.validator import check_sequence_rules_after

        outp = next(c for c in schema.commands if c.command == ":OUTP")
        issues: list[str] = []
        suggestions: list[str] = []
        # Simulate post-execution state where output is still ON (should fail).
        check_sequence_rules_after(outp, ":OUTP", "OFF", {"output": "ON"}, issues, suggestions)
        assert len(issues) == 1
        assert "Output should be turned OFF" in issues[0]

    def test_validate_sequence_rule_after_pass(self, schema: InstrumentSchema) -> None:
        from instr_core.validator import check_sequence_rules_after

        outp = next(c for c in schema.commands if c.command == ":OUTP")
        issues: list[str] = []
        suggestions: list[str] = []
        check_sequence_rules_after(outp, ":OUTP", "OFF", {"output": "OFF"}, issues, suggestions)
        assert len(issues) == 0


class TestRegistry:
    def test_registry_load(self) -> None:
        registry = Registry.load(FIXTURES_ROOT)
        assert len(registry) > 0
        instruments = registry.list_instruments()
        assert any("2600" in k for k in instruments)

    def test_lazy_loading(self) -> None:
        registry = Registry.load(FIXTURES_ROOT)
        # Before access, cache should be empty
        assert len(registry._cache) == 0
        schema = registry.get_schema("keithley/smu/2600")
        assert schema.instrument.manufacturer == "Keithley"
        # After access, cache should contain it
        assert len(registry._cache) == 1
        # Second access should hit cache
        schema2 = registry.get_schema("keithley/smu/2600")
        assert schema2 is schema

    def test_search_instruments(self) -> None:
        registry = Registry.load(FIXTURES_ROOT)
        results = registry.search_instruments(manufacturer="keithley")
        assert "keithley/smu/2600" in results

        results = registry.search_instruments(keyword="2600")
        assert "keithley/smu/2600" in results

        results = registry.search_instruments(manufacturer="nonexistent")
        assert len(results) == 0

    def test_empty_registry_no_sources_rejected(self) -> None:
        """Registry with no paths and no client must refuse to construct."""
        with pytest.raises(RuntimeError, match="Registry is empty"):
            Registry()

    def test_empty_paths_directory_rejected(self, tmp_path) -> None:
        """A path with no YAML files in it must also fail fast at startup."""
        empty_dir = tmp_path / "empty-registry"
        empty_dir.mkdir()
        with pytest.raises(RuntimeError, match="no YAML schemas were found"):
            Registry.load(empty_dir)

    def test_client_only_empty_index_is_allowed(self, tmp_path) -> None:
        """A client-backed registry may legitimately start with an empty
        index — the client can fetch schemas lazily."""

        class _StubClient:
            def __init__(self, cache_dir):
                self.cache_dir = cache_dir

            def get_schema(self, vendor, type_, model):  # pragma: no cover
                raise AssertionError("not exercised in this test")

        registry = Registry(client=_StubClient(tmp_path / "cache"))
        assert len(registry) == 0

    def test_concurrent_get_and_list(self, tmp_path) -> None:
        """Concurrent get_schema (with client fallback) and list_instruments
        must not raise ``dictionary changed size during iteration``."""
        import threading

        # Seed the registry with on-disk schemas so iteration has something
        # to walk while writers are mutating the index.
        root = tmp_path / "registry"
        for i in range(20):
            d = root / f"vendor{i:02d}" / "smu"
            d.mkdir(parents=True)
            (d / "model.yaml").write_text(SAMPLE_YAML, encoding="utf-8")

        class _StubClient:
            def __init__(self, cache_dir):
                self.cache_dir = cache_dir

            def get_schema(self, vendor, type_, model):
                return InstrumentSchema.model_validate(yaml.safe_load(SAMPLE_YAML))

        registry = Registry(paths=[root], client=_StubClient(tmp_path / "cache"))

        errors: list[BaseException] = []
        stop = threading.Event()

        def reader() -> None:
            try:
                while not stop.is_set():
                    registry.list_instruments()
                    registry.search_instruments(keyword="vendor")
                    len(registry)
            except BaseException as exc:  # pragma: no cover - failure path
                errors.append(exc)

        def writer(start: int) -> None:
            try:
                for i in range(start, start + 25):
                    registry.get_schema(f"new{i:03d}/type/model")
            except BaseException as exc:  # pragma: no cover - failure path
                errors.append(exc)

        threads = [threading.Thread(target=reader) for _ in range(3)]
        for i in range(3):
            threads.append(threading.Thread(target=writer, args=(i * 25,)))
        for t in threads[:3]:
            t.start()
        for t in threads[3:]:
            t.start()
        for t in threads[3:]:
            t.join()
        stop.set()
        for t in threads[:3]:
            t.join()

        assert not errors, f"concurrent access raised: {errors!r}"
        assert len(registry) == 20 + 75

    def test_concurrent_same_key_single_cached_instance(self, tmp_path) -> None:
        """All concurrent fetchers of an uncached key must see the same
        cached instance once the dust settles."""
        import threading

        class _StubClient:
            def __init__(self, cache_dir):
                self.cache_dir = cache_dir

            def get_schema(self, vendor, type_, model):
                return InstrumentSchema.model_validate(yaml.safe_load(SAMPLE_YAML))

        registry = Registry(client=_StubClient(tmp_path / "cache"))

        results: list[InstrumentSchema] = []
        results_lock = threading.Lock()

        def worker() -> None:
            schema = registry.get_schema("keithley/smu/2600")
            with results_lock:
                results.append(schema)

        threads = [threading.Thread(target=worker) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        first = results[0]
        assert all(r is first for r in results)


class TestServer:
    @pytest.fixture(scope="class")
    def mcp(self):
        registry = Registry.load(FIXTURES_ROOT)
        return create_server(registry)

    def test_list_instruments(self, mcp) -> None:
        result = mcp._tool_manager._tools["list_instruments"].fn()
        assert "keithley/smu/2600" in result.content[0].text

    def test_search_instruments(self, mcp) -> None:
        result = mcp._tool_manager._tools["search_instruments"].fn(manufacturer="keithley")
        assert "keithley/smu/2600" in result.content[0].text

        result = mcp._tool_manager._tools["search_instruments"].fn(keyword="2600")
        assert "keithley/smu/2600" in result.content[0].text

    def test_get_safety_limits(self, mcp) -> None:
        result = mcp._tool_manager._tools["get_safety_limits"].fn(instrument="keithley/smu/2600")
        assert "40" in result.content[0].text

    def test_validate_valid_command(self, mcp) -> None:
        state = {"source_mode": "VOLT", ":SENS:CURR:PROT": "0.01"}
        result = mcp._tool_manager._tools["validate_instrument_state"].fn(
            instrument="keithley/smu/2600",
            command=":SOUR:VOLT",
            argument="10",
            current_state=state,
        )
        assert "PASS" in result.content[0].text

    def test_validate_invalid_command(self, mcp) -> None:
        result = mcp._tool_manager._tools["validate_instrument_state"].fn(
            instrument="keithley/smu/2600",
            command=":SOUR:VOLT",
            argument="50",
            current_state={},
        )
        assert "FAIL" in result.content[0].text

    def test_validate_sequence(self, mcp) -> None:
        steps = [
            SequenceStep(command=":OUTP", argument="OFF"),
            SequenceStep(command=":SOUR:FUNC", argument="VOLT"),
        ]
        result = mcp._tool_manager._tools["validate_command_sequence"].fn(
            instrument="keithley/smu/2600", commands=steps
        )
        assert "PASS" in result.content[0].text

    def test_validate_sequence_missing_compliance(self, mcp) -> None:
        steps = [
            SequenceStep(command=":OUTP", argument="ON"),
        ]
        result = mcp._tool_manager._tools["validate_command_sequence"].fn(
            instrument="keithley/smu/2600", commands=steps
        )
        assert "FAIL" in result.content[0].text
        assert "Compliance must be configured" in result.content[0].text

    def test_validate_sequence_with_compliance(self, mcp) -> None:
        steps = [
            SequenceStep(command=":SENS:CURR:PROT", argument="0.01"),
            SequenceStep(command=":OUTP", argument="ON"),
        ]
        result = mcp._tool_manager._tools["validate_command_sequence"].fn(
            instrument="keithley/smu/2600", commands=steps
        )
        assert "PASS" in result.content[0].text

    def test_get_instrument_sop_prompt(self, mcp) -> None:
        result = mcp._prompt_manager._prompts["get_instrument_sop"].fn(
            instrument="keithley/smu/2600", operation="setup"
        )
        texts = [msg.content.text for msg in result]
        assert any("Keithley" in t for t in texts)
        assert any("yaml" in t.lower() for t in texts)

    def test_get_instrument_sop_unknown_instrument(self, mcp) -> None:
        """An unknown instrument must surface a friendly ValueError, not a
        bare 'not found in registry' message — and the message must point
        the caller back at `list_instruments`."""
        with pytest.raises(ValueError) as excinfo:
            mcp._prompt_manager._prompts["get_instrument_sop"].fn(
                instrument="nonexistent/smu/9999", operation="setup"
            )
        msg = str(excinfo.value)
        assert "nonexistent/smu/9999" in msg
        assert "list_instruments" in msg
        # The registry has at least one known instrument, so the hint
        # block must be present.
        assert "Known instruments include:" in msg

    def test_smu_safe_voltage_setup_unknown_instrument(self, mcp) -> None:
        with pytest.raises(ValueError) as excinfo:
            mcp._prompt_manager._prompts["smu_safe_voltage_setup"].fn(
                instrument="nonexistent/smu/9999", voltage="5"
            )
        msg = str(excinfo.value)
        assert "nonexistent/smu/9999" in msg
        assert "list_instruments" in msg

    def test_smu_safe_current_setup_unknown_instrument(self, mcp) -> None:
        with pytest.raises(ValueError) as excinfo:
            mcp._prompt_manager._prompts["smu_safe_current_setup"].fn(
                instrument="nonexistent/smu/9999", current="0.01"
            )
        msg = str(excinfo.value)
        assert "nonexistent/smu/9999" in msg
        assert "list_instruments" in msg

    def test_instrument_init_unknown_instrument(self, mcp) -> None:
        with pytest.raises(ValueError) as excinfo:
            mcp._prompt_manager._prompts["instrument_init"].fn(
                instrument="nonexistent/smu/9999"
            )
        msg = str(excinfo.value)
        assert "nonexistent/smu/9999" in msg
        assert "list_instruments" in msg


# =====================================================================
# Optional GlobalLimits, category field, non-SMU fixture coverage
# =====================================================================

SAMPLE_SCOPE_YAML = """
instrument:
  manufacturer: Keysight
  model: "DSOX1204G"
  category: scope
  description: "200 MHz oscilloscope"

global_limits:
  voltage: {max: 300.0, unit: "V"}

commands:
  - command: ":TIM:SCAL"
    description: "Set the horizontal time-per-division"
    parameters:
      - name: "scale"
        type: "float"
    range:
      min: 1.0e-9
      max: 50.0

  - command: ":CHAN1:DISP"
    parameters:
      - name: "state"
        type: "string"
        allowed_values: ["ON", "OFF"]
    sets_state:
      channel1: "$ARGUMENT_UPPER"

  - command: ":TRIG:SOUR"
    parameters:
      - name: "source"
        type: "string"
        allowed_values: ["CHAN1", "EXT", "LINE"]
    sets_state:
      trigger_source: "$ARGUMENT_UPPER"

  - command: ":MEAS:VPP?"
    forbidden_when:
      channel1: OFF
"""


def test_global_limits_optional_when_omitted() -> None:
    """A scope schema that declares only ``voltage`` must parse and the
    other dimensions must be ``None`` (not raise)."""
    schema = InstrumentSchema.model_validate(yaml.safe_load(SAMPLE_SCOPE_YAML))
    assert schema.global_limits.voltage is not None
    assert schema.global_limits.voltage.max == 300.0
    assert schema.global_limits.current is None
    assert schema.global_limits.power is None


def test_instrument_info_category_field() -> None:
    """The ``instrument.category`` field is preserved through parsing."""
    schema = InstrumentSchema.model_validate(yaml.safe_load(SAMPLE_SCOPE_YAML))
    assert schema.instrument.category == "scope"


def test_smu_fixture_carries_category() -> None:
    """The SMU fixture now carries ``category: smu`` so search_instruments
    by category can find it."""
    path = FIXTURES_ROOT / "keithley" / "smu" / "2600.yaml"
    schema = InstrumentSchema.model_validate(
        yaml.safe_load(path.read_text(encoding="utf-8"))
    )
    assert schema.instrument.category == "smu"


def test_check_global_limits_skips_undeclared_dimensions() -> None:
    """When the schema omits a limit dimension, ``check_global_limits``
    must not raise and must not flag the command."""
    from instr_core.validator import check_global_limits

    schema = InstrumentSchema.model_validate(yaml.safe_load(SAMPLE_SCOPE_YAML))
    issues: list[str] = []
    suggestions: list[str] = []
    # 1000 A would trip a current limit on any sourcing instrument, but
    # the scope schema declares no current limit, so this must be silent.
    check_global_limits(schema, ":SOUR:CURR", 1000.0, issues, suggestions)
    assert issues == [], f"expected no global-limit issue, got: {issues}"
    # Voltage IS declared, so a 1 kV signal must still be flagged.
    check_global_limits(schema, ":INP:VOLT", 1000.0, issues, suggestions)
    assert any("voltage max" in i for i in issues)


def test_validate_command_no_argument_skips_allowed_values() -> None:
    """When ``argument`` is ``None``, ``check_argument`` must not run —
    an empty argument is not the same as ``""`` and must not trigger an
    allowed_values mismatch."""
    schema = InstrumentSchema.model_validate(yaml.safe_load(SAMPLE_YAML))
    # :SOUR:FUNC has allowed_values=["VOLT", "CURR"]. With output=OFF the
    # requires pre-condition is satisfied, so the only thing that could
    # fail is the allowed_values check — which must be skipped.
    result = validate_command(schema, ":SOUR:FUNC", None, {"output": "OFF"})
    assert result.valid, f"expected valid, got: {result.issues}"


def test_arg_matches_allowed_numeric_edge_cases() -> None:
    """``_arg_matches_allowed`` must correctly handle 0, negative numbers
    and the empty string."""
    from instr_core.validator import _arg_matches_allowed

    assert _arg_matches_allowed("0", [0, 1, 2]) is True
    assert _arg_matches_allowed("-1", [-1, 0, 1]) is True
    assert _arg_matches_allowed("", ["ON", "OFF"]) is False
    assert _arg_matches_allowed("0.0", [0.0, 1.5]) is True


def test_forbidden_when_suggestion_is_generic() -> None:
    """``check_forbidden_when`` must no longer flip ON/OFF — for a
    multi-valued state key the suggestion must be the generic
    "ensure ... is not <forbidden>" wording."""
    from instr_core.validator import check_forbidden_when
    from instr_core.schema import CommandDef

    cmd = CommandDef(
        command=":MEAS:VPP?",
        forbidden_when={"trigger_source": "EXT"},
    )
    issues: list[str] = []
    suggestions: list[str] = []
    check_forbidden_when(cmd, {"trigger_source": "EXT"}, issues, suggestions)
    assert any("trigger_source=EXT" in i for i in issues)
    # The fix must not invent a binary "INT"/"ON" suggestion.
    assert all("ON" not in s and "OFF" not in s for s in suggestions), suggestions
    assert any("is not EXT" in s for s in suggestions)


def test_compliance_required_without_parameter_emits_schema_bug() -> None:
    """If a schema declares ``compliance_required: true`` but no
    ``compliance_parameter``, validate_command must surface a "schema
    bug" issue rather than silently fall back to the literal string
    "compliance" (which would never match a real state key)."""
    from instr_core.schema import CommandDef, ParameterDef, Safety

    cmd = CommandDef(
        command=":SOUR:VOLT",
        parameters=[ParameterDef(name="voltage", **{"type": "float"})],
        safety=Safety(compliance_required=True),
    )
    schema = InstrumentSchema(
        instrument={
            "manufacturer": "Acme",
            "model": "X",
        },
        global_limits={},
        commands=[cmd],
    )
    result = validate_command(schema, ":SOUR:VOLT", "1.0", {})
    assert not result.valid
    assert any("Schema bug" in i for i in result.issues), result.issues


def test_check_argument_skips_multi_parameter_commands() -> None:
    """Multi-parameter commands must not trigger a false-positive
    allowed_values cascade (single arg cannot match every parameter)."""
    from instr_core.validator import check_argument
    from instr_core.schema import CommandDef, ParameterDef

    cmd = CommandDef(
        command=":CONF:TEMP",
        parameters=[
            ParameterDef(name="sensor", **{"type": "string"},
                         allowed_values=["TC", "RTD"]),
            ParameterDef(name="type", **{"type": "string"},
                         allowed_values=["J", "K", "T"]),
        ],
    )
    issues: list[str] = []
    suggestions: list[str] = []
    check_argument(cmd, "TC,J", issues, suggestions)
    assert issues == [], f"multi-param should be skipped, got: {issues}"


class TestRegistrySearchByCategory:
    """Cover Registry.search_instruments(category=...) with both the SMU
    and the new scope fixtures so the engine's generality is exercised."""

    def test_search_by_category_smu(self) -> None:
        registry = Registry.load(FIXTURES_ROOT)
        results = registry.search_instruments(category="smu")
        assert "keithley/smu/2600" in results
        assert all("/smu/" in k for k in results)

    def test_search_by_category_scope(self) -> None:
        registry = Registry.load(FIXTURES_ROOT)
        results = registry.search_instruments(category="scope")
        assert "keysight/scope/dsox1204g" in results
        assert all("/scope/" in k for k in results)

    def test_search_by_category_no_match(self) -> None:
        registry = Registry.load(FIXTURES_ROOT)
        results = registry.search_instruments(category="dmm")
        assert results == []

    def test_search_combines_category_and_manufacturer(self) -> None:
        registry = Registry.load(FIXTURES_ROOT)
        results = registry.search_instruments(manufacturer="keithley", category="smu")
        assert results == ["keithley/smu/2600"]
        # Mismatched combination yields nothing.
        results = registry.search_instruments(manufacturer="keithley", category="scope")
        assert results == []


class TestScopeFixtureValidation:
    """End-to-end checks that a non-SMU schema can be loaded and
    validated by the same engine the SMU uses — proving the engine is
    truly category-agnostic."""

    @pytest.fixture(scope="class")
    def scope_schema(self) -> InstrumentSchema:
        path = FIXTURES_ROOT / "keysight" / "scope" / "dsox1204g.yaml"
        return InstrumentSchema.model_validate(
            yaml.safe_load(path.read_text(encoding="utf-8"))
        )

    def test_scope_schema_parses(self, scope_schema: InstrumentSchema) -> None:
        assert scope_schema.instrument.manufacturer == "Keysight"
        assert scope_schema.instrument.category == "scope"

    def test_scope_per_command_range_still_enforced(
        self, scope_schema: InstrumentSchema
    ) -> None:
        """No global current limit, but per-command ``range`` must still
        catch out-of-range values."""
        result = validate_command(scope_schema, ":TIM:SCAL", "1000", {})
        assert not result.valid
        assert any("out of range" in i for i in result.issues)

    def test_scope_allowed_values_enforced(
        self, scope_schema: InstrumentSchema
    ) -> None:
        result = validate_command(scope_schema, ":TRIG:SOUR", "BUS", {})
        assert not result.valid
        assert any("Invalid value 'BUS'" in i for i in result.issues)

    def test_scope_forbidden_when_uses_generic_suggestion(
        self, scope_schema: InstrumentSchema
    ) -> None:
        """`:MEAS:VPP?` is forbidden when `channel1=OFF` — verify the
        suggestion does NOT mention ON/OFF flips."""
        result = validate_command(
            scope_schema, ":MEAS:VPP?", None, {"channel1": "OFF"}
        )
        assert not result.valid
        assert any("channel1=OFF" in i for i in result.issues)
        assert any("is not OFF" in s for s in result.suggestions)


class TestScopeMeasureSetupPrompt:
    @pytest.fixture(scope="class")
    def mcp(self):
        registry = Registry.load(FIXTURES_ROOT)
        return create_server(registry)

    def test_scope_measure_setup_known_instrument(self, mcp) -> None:
        result = mcp._prompt_manager._prompts["scope_measure_setup"].fn(
            instrument="keysight/scope/dsox1204g", measurement="Vpp"
        )
        texts = [msg.content.text for msg in result]
        assert any("Keysight" in t for t in texts)
        assert any("DSOX1204G" in t for t in texts)
        # Critically, no hardcoded SCPI command should leak into the prompt.
        assert all(":SOUR:VOLT" not in t for t in texts)
        assert all(":OUTP" not in t for t in texts)

    def test_scope_measure_setup_unknown_instrument(self, mcp) -> None:
        with pytest.raises(ValueError) as excinfo:
            mcp._prompt_manager._prompts["scope_measure_setup"].fn(
                instrument="nonexistent/scope/9999"
            )
        msg = str(excinfo.value)
        assert "nonexistent/scope/9999" in msg
        assert "list_instruments" in msg
