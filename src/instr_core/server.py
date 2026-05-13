"""FastMCP server implementation for instr-core."""

from __future__ import annotations

import logging

import yaml
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.prompts import base
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.types import (
    CallToolResult,
    Completion,
    ListResourcesRequest,
    ListResourcesResult,
    PromptReference,
    Resource,
    TextContent,
    ToolAnnotations,
)
from pydantic import BaseModel

from .schema import InstrumentSchema
from .validator import Registry, check_sequence_rules_after, validate_command


class SequenceStep(BaseModel):
    """A single step in a command sequence."""

    command: str
    argument: str | None = None
    state: dict[str, str] | None = None


_RESOURCE_PAGE_SIZE = 100


def _tool_result(text: str, is_error: bool = False) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], isError=is_error)


def create_server(registry: Registry) -> FastMCP:
    """Create a FastMCP server instance with all tools, prompts and resources."""
    logger = logging.getLogger("instr_core.server")

    mcp = FastMCP(
        "instr-core",
        instructions=(
            "instr-core provides safe, verifiable instrument-control context for "
            "AI coding assistants. Use 'list_instruments' to see available "
            "instruments, 'get_command_tree' to explore SCPI commands, and "
            "'validate_instrument_state' to check command safety before generating code."
        ),
        version="0.2.0",
    )

    def _get_schema(instrument: str) -> InstrumentSchema:
        try:
            return registry.get_schema(instrument)
        except KeyError as exc:
            raise ValueError(str(exc))

    def _require_known_instrument(instrument: str, action: str) -> InstrumentSchema:
        """Resolve an instrument schema or raise a user-friendly ``ValueError``.

        Used by prompt handlers to surface a consistent, actionable error
        message when the caller passes an unknown instrument key, instead
        of letting a bare ``KeyError`` translated to ``ValueError`` leak
        out with no recovery hint.
        """
        try:
            return registry.get_schema(instrument)
        except KeyError as exc:
            known = registry.list_instruments()
            if known:
                preview = ", ".join(known[:5])
                more = f" (+{len(known) - 5} more)" if len(known) > 5 else ""
                hint = f" Known instruments include: {preview}{more}."
            else:
                hint = ""
            raise ValueError(
                f"Cannot {action}: instrument '{instrument}' is not in the registry."
                f"{hint} Call the 'list_instruments' tool to see what's loaded."
            ) from exc

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Server Status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    def server_status() -> CallToolResult:
        """Return the health status and basic runtime information of the server."""
        logger.debug("server_status called")
        try:
            count = len(registry)
            healthy = count > 0
            status_text = (
                f"instr-core MCP server\n"
                f"  Version: 0.2.0\n"
                f"  Status: {'healthy' if healthy else 'degraded'}\n"
                f"  Indexed instruments: {count}"
            )
            logger.debug("server_status: %s, %d instruments", "healthy" if healthy else "degraded", count)
            return _tool_result(status_text, is_error=not healthy)
        except Exception as exc:
            logger.error("server_status error: %s", exc)
            return _tool_result(f"Error checking server status: {exc}", is_error=True)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Validate Command",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    def validate_instrument_state(
        instrument: str,
        command: str,
        argument: str | None = None,
        current_state: dict[str, str] | None = None,
    ) -> CallToolResult:
        """Validate a SCPI command against the instrument safety schema."""
        logger.debug(
            "validate_instrument_state: instrument=%s command=%s argument=%s",
            instrument, command, argument,
        )
        try:
            schema = _get_schema(instrument)
            state = current_state or {}
            result = validate_command(schema, command, argument, state)
        except Exception as exc:
            logger.error("validate_instrument_state error: %s", exc)
            return _tool_result(f"Error validating command: {exc}", is_error=True)

        arg_str = argument or ""
        if result.valid:
            logger.debug("validate_instrument_state: PASS %s %s", command, arg_str)
            text = f"PASS: Command '{command} {arg_str}' is valid for {instrument}."
            return _tool_result(text)

        logger.debug(
            "validate_instrument_state: FAIL %s %s (%d issues)",
            command, arg_str, len(result.issues),
        )
        issues_str = "\n".join(f"  {i + 1}. {issue}" for i, issue in enumerate(result.issues))
        suggestions_str = ""
        if result.suggestions:
            sugg = "\n".join(f"  {i + 1}. {s}" for i, s in enumerate(result.suggestions))
            suggestions_str = f"\nSuggestions:\n{sugg}"
        text = (
            f"FAIL: Command '{command} {arg_str}' has {len(result.issues)} issue(s):\n"
            f"{issues_str}{suggestions_str}"
        )
        return _tool_result(text, is_error=True)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="List Instruments",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    def list_instruments() -> CallToolResult:
        """List all loaded instruments in the registry."""
        logger.debug("list_instruments called")
        try:
            keys = registry.list_instruments()
            lines = []
            for key in keys:
                meta = registry.get_metadata(key)
                if meta:
                    desc = meta.get("description") or "no description"
                    lines.append(f"- {key} — {meta['manufacturer']} {meta['model']} ({desc})")
                else:
                    lines.append(f"- {key}")
            logger.debug("list_instruments returned %d instrument(s)", len(lines))
            return _tool_result(f"Loaded {len(lines)} instrument(s):\n" + "\n".join(lines))
        except Exception as exc:
            logger.error("list_instruments error: %s", exc)
            return _tool_result(f"Error listing instruments: {exc}", is_error=True)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Search Instruments",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    def search_instruments(
        manufacturer: str | None = None,
        keyword: str | None = None,
        category: str | None = None,
    ) -> CallToolResult:
        """Search instruments by manufacturer prefix, category, or keyword substring."""
        logger.debug(
            "search_instruments: manufacturer=%s keyword=%s category=%s",
            manufacturer, keyword, category,
        )
        try:
            results = registry.search_instruments(
                manufacturer=manufacturer, keyword=keyword, category=category
            )
            if not results:
                logger.debug("search_instruments: no matches")
                return _tool_result("No instruments found matching the criteria.")

            lines = []
            for key in results:
                meta = registry.get_metadata(key)
                if meta:
                    desc = meta.get("description") or "no description"
                    lines.append(f"- {key} — {meta['manufacturer']} {meta['model']} ({desc})")
                else:
                    lines.append(f"- {key}")
            logger.debug("search_instruments returned %d instrument(s)", len(results))
            return _tool_result(f"Found {len(results)} instrument(s):\n" + "\n".join(lines))
        except Exception as exc:
            logger.error("search_instruments error: %s", exc)
            return _tool_result(f"Error searching instruments: {exc}", is_error=True)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Get Command Tree",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    def get_command_tree(instrument: str) -> CallToolResult:
        """Get the full SCPI command tree for an instrument."""
        logger.debug("get_command_tree: instrument=%s", instrument)
        try:
            schema = _get_schema(instrument)
            lines = []
            for cmd in schema.commands:
                desc = cmd.description or ""
                if cmd.parameters:
                    parts = []
                    for param in cmd.parameters:
                        if param.allowed_values:
                            parts.append(f"{param.name}: {param.param_type} {param.allowed_values}")
                        else:
                            parts.append(f"{param.name}: {param.param_type}")
                    params_str = f" ({', '.join(parts)})"
                else:
                    params_str = ""
                lines.append(f"- {cmd.command}{params_str} — {desc}")
            logger.debug("get_command_tree: returned %d commands for %s", len(lines), instrument)
            return _tool_result(
                f"{schema.instrument.manufacturer} {schema.instrument.model} — "
                f"{len(lines)} commands:\n" + "\n".join(lines)
            )
        except Exception as exc:
            logger.error("get_command_tree error: %s", exc)
            return _tool_result(f"Error getting command tree: {exc}", is_error=True)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Get Safety Limits",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    def get_safety_limits(instrument: str) -> CallToolResult:
        """Get the global safety limits for an instrument."""
        logger.debug("get_safety_limits: instrument=%s", instrument)
        try:
            schema = _get_schema(instrument)
            limits = schema.global_limits
            declared: list[tuple[str, object, str]] = []
            if limits.voltage is not None:
                declared.append(("Voltage", limits.voltage.max, limits.voltage.unit))
            if limits.current is not None:
                declared.append(("Current", limits.current.max, limits.current.unit))
            if limits.power is not None:
                declared.append(("Power", limits.power.max, limits.power.unit))
            logger.debug(
                "get_safety_limits: %s declared=%s",
                instrument,
                [name for name, _, _ in declared],
            )
            if not declared:
                body = "  (no global limits declared in schema)"
            else:
                body = "\n".join(f"  {name}: {value} {unit}" for name, value, unit in declared)
            return _tool_result(
                f"Safety limits for {schema.instrument.manufacturer} {schema.instrument.model}:\n"
                f"{body}"
            )
        except Exception as exc:
            logger.error("get_safety_limits error: %s", exc)
            return _tool_result(f"Error getting safety limits: {exc}", is_error=True)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Get Command Detail",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    def get_command_detail(instrument: str, command: str) -> CallToolResult:
        """Get detailed constraints for a specific SCPI command."""
        logger.debug("get_command_detail: instrument=%s command=%s", instrument, command)
        try:
            schema = _get_schema(instrument)
            cmd_def = next((c for c in schema.commands if c.command == command), None)
            if cmd_def is None:
                logger.warning("get_command_detail: command '%s' not found in %s", command, instrument)
                return _tool_result(
                    f"Command '{command}' not found in instrument schema.", is_error=True
                )

            details = [f"Command: {cmd_def.command}"]
            if cmd_def.description:
                details.append(f"Description: {cmd_def.description}")
            if cmd_def.parameters:
                params_str = "\n".join(
                    (
                        f"  - {p.name}: {p.param_type} allowed={p.allowed_values}"
                        if p.allowed_values
                        else f"  - {p.name}: {p.param_type}"
                    )
                    for p in cmd_def.parameters
                )
                details.append(f"Parameters:\n{params_str}")
            if cmd_def.range is not None:
                details.append(f"Range: [{cmd_def.range.min}, {cmd_def.range.max}]")
            if cmd_def.requires:
                reqs = "\n".join(f"  {k}={v}" for k, v in cmd_def.requires.items())
                details.append(f"Requires:\n{reqs}")
            if cmd_def.forbidden_when:
                forb = "\n".join(f"  {k}={v}" for k, v in cmd_def.forbidden_when.items())
                details.append(f"Forbidden when:\n{forb}")
            if cmd_def.safety is not None:
                if cmd_def.safety.compliance_required is not None:
                    details.append(f"Compliance required: {cmd_def.safety.compliance_required}")
                if cmd_def.safety.compliance_parameter:
                    details.append(f"Compliance parameter: {cmd_def.safety.compliance_parameter}")
                if cmd_def.safety.sequence:
                    parts = []
                    for s in cmd_def.safety.sequence:
                        attrs = f"before={s.before!r} after={s.after!r}"
                        if s.require_state_keys_present:
                            attrs += f" require_state_keys_present={s.require_state_keys_present}"
                        if s.expect_state:
                            attrs += f" expect_state={s.expect_state}"
                        parts.append(f"  {attrs} msg={s.message}")
                    details.append(f"Sequence rules:\n" + "\n".join(parts))
            return _tool_result("\n".join(details))
        except Exception as exc:
            logger.error("get_command_detail error: %s", exc)
            return _tool_result(f"Error getting command detail: {exc}", is_error=True)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Validate Sequence",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
        )
    )
    def validate_command_sequence(
        instrument: str,
        commands: list[SequenceStep],
    ) -> CallToolResult:
        """Validate a sequence of SCPI commands against the instrument safety schema."""
        logger.debug("validate_command_sequence: instrument=%s steps=%d", instrument, len(commands))
        try:
            schema = _get_schema(instrument)
            cumulative_state: dict[str, str] = {}
            all_valid = True
            step_results: list[str] = []

            for i, step in enumerate(commands):
                if step.state:
                    cumulative_state.update(step.state)
                result = validate_command(schema, step.command, step.argument, cumulative_state)
                arg_str = step.argument or ""

                # Update state so after-rules can be checked against post-execution state.
                _update_state(cumulative_state, schema, step.command, step.argument)
                cmd_def = next((c for c in schema.commands if c.command == step.command), None)
                after_issues: list[str] = []
                after_suggestions: list[str] = []
                if cmd_def is not None:
                    check_sequence_rules_after(
                        cmd_def, step.command, step.argument, cumulative_state, after_issues, after_suggestions
                    )

                combined_issues = result.issues + after_issues
                if not combined_issues:
                    step_results.append(f"  Step {i + 1}: {step.command} {arg_str} — PASS")
                else:
                    all_valid = False
                    issues = "\n".join(f"    - {issue}" for issue in combined_issues)
                    step_results.append(f"  Step {i + 1}: {step.command} {arg_str} — FAIL\n{issues}")

            summary = "ALL PASS" if all_valid else "HAS FAILURES"
            logger.debug("validate_command_sequence: %s %s", instrument, summary)
            return _tool_result(
                f"Sequence validation for {instrument} — {summary} ({len(step_results)} steps):\n"
                + "\n".join(step_results)
            )
        except Exception as exc:
            logger.error("validate_command_sequence error: %s", exc)
            return _tool_result(f"Error validating command sequence: {exc}", is_error=True)

    @mcp.prompt()
    def get_instrument_sop(instrument: str, operation: str = "setup") -> list[base.Message]:
        """Return a safe instrument SOP prompt containing the full schema context."""
        schema = _require_known_instrument(instrument, "generate SOP")
        limits = schema.global_limits
        yaml_text = yaml.dump(
            schema.model_dump(by_alias=True, exclude_none=True),
            allow_unicode=True,
            sort_keys=False,
        )
        declared_limits: list[str] = []
        if limits.voltage is not None:
            declared_limits.append(
                f"- Voltage: {limits.voltage.max} {limits.voltage.unit}"
            )
        if limits.current is not None:
            declared_limits.append(
                f"- Current: {limits.current.max} {limits.current.unit}"
            )
        if limits.power is not None:
            declared_limits.append(
                f"- Power: {limits.power.max} {limits.power.unit}"
            )
        if declared_limits:
            limits_block = "Global safety limits:\n" + "\n".join(declared_limits) + "\n\n"
        else:
            limits_block = (
                "Global safety limits: none declared by this schema (per-command "
                "ranges still apply).\n\n"
            )
        return [
            base.UserMessage(
                f"Generate safe PyVISA code for {schema.instrument.manufacturer} "
                f"{schema.instrument.model} (operation: {operation}).\n\n"
                f"Use the following instrument schema as the single source of truth. "
                f"Respect all safety limits, state requirements, and forbidden conditions:\n\n"
                f"```yaml\n{yaml_text}\n```\n\n"
                f"{limits_block}"
                f"Respect all sequencing rules, forbidden conditions, and state requirements "
                f"declared in the schema. Never exceed the declared global limits."
            ),
            base.AssistantMessage(
                f"I'll generate safe {operation} code for {schema.instrument.manufacturer} "
                f"{schema.instrument.model}, strictly following the schema constraints."
            ),
        ]

    @mcp.prompt()
    def smu_safe_voltage_setup(instrument: str, voltage: str = "10") -> list[base.Message]:
        """Step-by-step guide for safely configuring and applying voltage (SMU-specific)."""
        _require_known_instrument(instrument, "generate voltage setup guide")
        return [
            base.UserMessage(
                f"I need to safely set up {instrument} to output {voltage}V. "
                "Please follow this safe voltage setup procedure:\n\n"
                f"1. First, call `get_safety_limits` for {instrument} to check the voltage limit\n"
                f"2. Call `get_command_detail` for `:SOUR:VOLT` to understand constraints\n"
                "3. Validate the command with `validate_instrument_state`:\n"
                "   - command: `:SOUR:FUNC`, argument: `VOLT`, current_state: {{output: OFF}}\n"
                "   - command: `:SENS:CURR:PROT`, argument: `<compliance_value>`\n"
                f"   - command: `:SOUR:VOLT`, argument: `{voltage}`\n"
                "4. If all validations pass, invoke the `get_instrument_sop` prompt with operation=`setup` to get the full schema context for code generation\n"
                "5. Never enable output (`:OUTP ON`) without setting compliance first!"
            ),
            base.AssistantMessage(
                f"I'll help you safely configure {instrument} for {voltage}V output. "
                "Let me start by checking the safety limits and validating each "
                "command step by step."
            ),
        ]

    @mcp.prompt()
    def smu_safe_current_setup(instrument: str, current: str = "0.01") -> list[base.Message]:
        """Step-by-step guide for safely configuring and applying current (SMU-specific)."""
        _require_known_instrument(instrument, "generate current setup guide")
        return [
            base.UserMessage(
                f"I need to safely set up {instrument} to output {current}A. "
                "Please follow this safe current setup procedure:\n\n"
                f"1. First, call `get_safety_limits` for {instrument} to check the current limit\n"
                f"2. Call `get_command_detail` for `:SOUR:CURR` to understand constraints\n"
                "3. Validate the command with `validate_instrument_state`:\n"
                "   - command: `:SOUR:FUNC`, argument: `CURR`, current_state: {{output: OFF}}\n"
                "   - command: `:SENS:VOLT:PROT`, argument: `<compliance_value>`\n"
                f"   - command: `:SOUR:CURR`, argument: `{current}`\n"
                "4. If all validations pass, invoke the `get_instrument_sop` prompt with operation=`setup` to get the full schema context for code generation\n"
                "5. Never enable output without setting compliance first!"
            ),
            base.AssistantMessage(
                f"I'll help you safely configure {instrument} for {current}A output. "
                "Let me validate each step before generating any code."
            ),
        ]

    @mcp.prompt()
    def scpi_safety_guide() -> list[base.Message]:
        """General guide on how to use instr-core for safe SCPI instrument control."""
        return [
            base.UserMessage("How should I use instr-core to write safe instrument control code?"),
            base.AssistantMessage(
                "Here's the recommended workflow for safe instrument control with instr-core:\n\n"
                "**Step 1: Discover**\n"
                "- `list_instruments` — see available instruments\n"
                "- `search_instruments` — find instruments by manufacturer or keyword\n"
                "- `get_command_tree` — explore SCPI commands for an instrument\n\n"
                "**Step 2: Understand Constraints**\n"
                "- `get_safety_limits` — check max voltage/current/power\n"
                "- `get_command_detail` — understand range, requires, forbidden_when, "
                "safety rules\n\n"
                "**Step 3: Validate Before Code Generation**\n"
                "- `validate_instrument_state` — check individual commands\n"
                "- `validate_command_sequence` — verify multi-step sequences\n\n"
                "**Step 4: Generate Safe Code**\n"
                "- `get_instrument_sop` — get the full instrument schema context for generating safe PyVISA code\n\n"
                "**Critical Rules:**\n"
                "- Respect all `requires` pre-conditions before executing commands\n"
                "- Never exceed global limits (check with `get_safety_limits`)\n"
                "- Obey `forbidden_when` constraints and `safety.sequence` ordering rules\n"
                "- Use `validate_instrument_state` as the source of truth, not my suggestions"
            ),
        ]

    @mcp.prompt()
    def instrument_init(instrument: str) -> list[base.Message]:
        """Generate a safe instrument initialization sequence."""
        schema = _require_known_instrument(instrument, "generate init sequence")
        yaml_text = yaml.dump(
            schema.model_dump(by_alias=True, exclude_none=True),
            allow_unicode=True,
            sort_keys=False,
        )
        return [
            base.UserMessage(f"Generate a safe initialization sequence for {instrument}."),
            base.AssistantMessage(
                f"I'll create a safe initialization sequence for {instrument}. Let me:\n\n"
                "1. Check safety limits with `get_safety_limits`\n"
                "2. Get the command tree with `get_command_tree`\n"
                "3. Inspect the schema for required pre-conditions (e.g. output state, "
                "compliance, ranges, sequencing rules)\n"
                "4. Validate each step with `validate_instrument_state` before proceeding\n"
                "5. Generate code using the full schema context below:\n\n"
                f"```yaml\n{yaml_text}\n```\n\n"
                "Shall I proceed?"
            ),
        ]

    @mcp.prompt()
    def scope_measure_setup(instrument: str, measurement: str = "voltage") -> list[base.Message]:
        """Schema-driven guide for measurement-oriented instruments (scopes, DMMs, spectrum analysers).

        Unlike ``smu_safe_voltage_setup`` / ``smu_safe_current_setup``, this
        prompt hardcodes no SCPI commands. It instructs the AI to discover
        the relevant capture / measurement commands from the schema at
        runtime via ``get_command_tree`` and ``get_command_detail``, then
        validate each step with ``validate_instrument_state`` before
        emitting code. This keeps the prompt usable for any instrument
        whose primary role is *measuring*, not *sourcing*.
        """
        schema = _require_known_instrument(instrument, "generate measurement setup")
        return [
            base.UserMessage(
                f"I need to safely configure {instrument} to take a {measurement} measurement. "
                "Please follow this measurement-setup procedure:\n\n"
                f"1. Call `get_command_tree` for {instrument} to see what commands the schema declares\n"
                f"2. Call `get_safety_limits` to learn the declared input/output limits (some dimensions may be absent for purely measurement instruments)\n"
                "3. For each command you plan to send, call `get_command_detail` to read its `requires`, `forbidden_when`, `range`, and `safety.sequence` constraints\n"
                "4. Validate every step with `validate_instrument_state`, passing the cumulative state you have built so far\n"
                "5. Once all steps validate, invoke the `get_instrument_sop` prompt with operation=`measure` to get the full schema as code-generation context\n"
                "6. Never assume a command exists if it is not in the schema \u2014 the schema is the single source of truth."
            ),
            base.AssistantMessage(
                f"I'll configure {schema.instrument.manufacturer} {schema.instrument.model} "
                f"for a {measurement} measurement strictly from the schema, validating each "
                "step before generating any code."
            ),
        ]

    @mcp._mcp_server.list_resources()
    async def handle_list_resources(
        req: ListResourcesRequest,
    ) -> ListResourcesResult:
        """Return paginated instrument resources."""
        cursor_str = req.params.cursor if req.params else None
        cursor = int(cursor_str) if cursor_str else 0

        all_keys = registry.list_instruments()
        batch = all_keys[cursor : cursor + _RESOURCE_PAGE_SIZE]

        resources: list[Resource] = []
        for key in batch:
            meta = registry.get_metadata(key)
            if meta:
                resources.append(
                    Resource(
                        uri=f"instr://{key}",
                        name=f"{meta['manufacturer']} {meta['model']}",
                        description=meta.get("description") or None,
                        mimeType="application/x-yaml",
                    )
                )
            else:
                resources.append(
                    Resource(
                        uri=f"instr://{key}",
                        name=key,
                        mimeType="application/x-yaml",
                    )
                )

        next_cursor = (
            str(cursor + _RESOURCE_PAGE_SIZE)
            if cursor + _RESOURCE_PAGE_SIZE < len(all_keys)
            else None
        )
        return ListResourcesResult(resources=resources, nextCursor=next_cursor)

    @mcp._mcp_server.read_resource()
    async def handle_read_resource(uri: str) -> list[ReadResourceContents]:
        """Read a schema YAML by its instr:// URI."""
        try:
            uri_str = str(uri)
            prefix = "instr://"
            if not uri_str.startswith(prefix):
                raise ValueError(f"Invalid instr-core resource URI: {uri_str}")
            key = uri_str[len(prefix) :]
            schema = _get_schema(key)
            yaml_text = yaml.dump(
                schema.model_dump(by_alias=True, exclude_none=True),
                allow_unicode=True,
                sort_keys=False,
            )
            return [ReadResourceContents(content=yaml_text, mime_type="application/x-yaml")]
        except ValueError:
            raise
        except Exception as exc:
            logger.error("handle_read_resource error: %s", exc)
            raise ValueError(f"Error reading resource {uri}: {exc}")

    @mcp.completion()
    async def handle_completion(ref, argument, context):
        """Provide completions for prompt arguments.

        Per the MCP ``completion/complete`` spec, the ``ref`` field is
        ``ResourceTemplateReference | PromptReference``; **tool argument
        completion is not part of the protocol**.  Calls of the form
        ``validate_instrument_state ?instrument=<tab>`` therefore never
        reach this handler.  Supporting tool-argument completion would
        require a protocol extension, not a server-side change.
        """
        if isinstance(ref, PromptReference) and argument.name == "instrument":
            partial = argument.value.lower()
            all_keys = registry.list_instruments()
            matches = [k for k in all_keys if partial in k.lower()]
            return Completion(values=matches[:50], total=len(matches), hasMore=len(matches) > 50)
        return None

    return mcp


def _update_state(
    state: dict[str, str],
    schema: InstrumentSchema,
    command: str,
    argument: str | None,
) -> None:
    """Update cumulative state based on command execution semantics.

    Commands not present in the schema cannot be tracked — the schema is the
    single source of truth.  If an author wants a command to affect state,
    they must declare it via ``sets_state`` in the YAML schema.

    The ``schema`` parameter is used as the command lookup source; the
    cumulative ``state`` dict is mutated in place using the ``sets_state``
    declarations of the matching :class:`CommandDef`.
    """
    cmd_def = next((c for c in schema.commands if c.command == command), None)
    if cmd_def is not None:
        for key, template in cmd_def.sets_state.items():
            if template == "$ARGUMENT":
                value = argument
            elif template == "$ARGUMENT_UPPER":
                value = argument.upper() if argument else None
            else:
                value = template
            if value is not None:
                state[key] = value
