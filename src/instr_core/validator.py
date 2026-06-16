"""Instrument registry loader and SCPI command validator."""

from __future__ import annotations

import logging
import re
import threading
from pathlib import Path

import yaml

from .schema import CommandDef, InstrumentSchema, SequenceRule

logger = logging.getLogger(__name__)


def _strip_yaml_value(line: str) -> str:
    """Extract the raw scalar value from a single ``key: value`` YAML line.

    Handles common quoting styles and YAML anchors (e.g. ``*id001``) so
    that the fast metadata path does not need a full YAML parser.
    """
    # Split on the first colon, ignoring anything before it.
    _, _, raw = line.partition(":")
    raw = raw.strip()
    # Strip matching quotes (single, double, or folded literals).
    if len(raw) >= 2:
        if raw[0] == raw[-1] and raw[0] in ('"', "'", "|", ">"):
            raw = raw[1:-1]
    # YAML anchors are not meaningful for display metadata.
    if raw.startswith("*"):
        raw = raw[1:]
    return raw.strip()


if False:
    # Imported lazily at runtime to keep the module light; type checkers still
    # resolve the forward reference because of the ``from __future__`` import.
    from .registry_client import RegistryClient


class Registry:
    """Lazy-loading instrument registry.

    Scans local registry directories or delegates to a :class:`RegistryClient`
    to build an index of available instruments. YAML files are parsed on first
    access and cached thereafter.

    Concurrency
    -----------
    Registry instances are safe to share across threads. Mutations of the
    in-memory ``_index`` and ``_cache`` dicts are serialized by an internal
    :class:`threading.RLock`, and read paths take a snapshot under the lock
    before iterating. The blocking I/O performed while lazily loading a
    schema (disk read or remote fetch) is done outside the lock so that
    concurrent readers are not blocked by network latency. The stdio MCP
    transport is single-threaded today, but SSE / streamable-HTTP
    transports may dispatch tool calls concurrently, and the registry is
    the only mutable state shared between them.

    Empty-registry protection
    -------------------------
    A registry with no indexed schemas and no :class:`RegistryClient`
    fallback cannot serve any tool call. Constructing such a registry
    raises :class:`RuntimeError` so that the failure surfaces at startup
    rather than as a confusing ``KeyError`` from the first incoming
    request.
    """

    def __init__(
        self,
        paths: list[str | Path] | None = None,
        client: RegistryClient | None = None,
    ) -> None:
        self._paths = [Path(p) for p in paths] if paths else []
        self._client = client
        self._index: dict[str, Path] = {}
        self._cache: dict[str, InstrumentSchema] = {}
        # RLock so that helpers can recurse (e.g. ``get_metadata`` falling
        # back to ``get_schema``) without self-deadlocking.
        self._lock = threading.RLock()
        self._scan()
        self._check_usable()

    def _check_usable(self) -> None:
        """Refuse to construct a registry that can never serve a request.

        A registry is usable if it has at least one indexed schema, or if it
        has a :class:`RegistryClient` that can lazily fetch schemas. Without
        either, every tool call would surface as a "not found" error at
        runtime; failing fast at construction gives the operator a chance
        to fix the configuration before the server accepts connections.
        """
        if self._index or self._client is not None:
            return

        if self._paths:
            paths_repr = ", ".join(str(p) for p in self._paths)
            detail = (
                f"no YAML schemas were found in the configured registry paths: {paths_repr}"
            )
        else:
            detail = "no registry paths were provided and no RegistryClient was attached"

        raise RuntimeError(
            "Registry is empty and has no fallback: "
            f"{detail}. "
            "Pass at least one directory containing *.yaml schemas to "
            "Registry.load(), or attach a RegistryClient via "
            "Registry.from_client() so schemas can be fetched on demand."
        )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, *paths: str | Path) -> Registry:
        """Create a registry from one or more directory paths.

        Later paths override earlier ones for duplicate keys.
        """
        return cls(list(paths))

    @classmethod
    def from_client(cls, client: RegistryClient) -> Registry:
        """Create a registry backed by a remote :class:`RegistryClient`."""
        return cls(client=client)

    @classmethod
    def from_package(cls, package: str = "instr_core", subpath: str = "registry") -> Registry:
        """Create a registry from package resources using importlib.resources.

        This guarantees that YAML files are found regardless of how the package
        was installed (editable, wheel, etc.).
        """
        import importlib.resources as pkg_resources

        root = pkg_resources.files(package).joinpath(subpath)
        return cls.load(str(root))

    def _scan(self) -> None:
        for dir_path in self._paths:
            if not dir_path.exists():
                raise FileNotFoundError(f"Registry directory does not exist: {dir_path}")
            self._walk(dir_path)
        if self._client is not None:
            self._scan_client_cache()

    def _scan_client_cache(self) -> None:
        if self._client is None:
            return
        cache_dir = self._client.cache_dir
        if not cache_dir.exists():
            return
        for pattern in ("*.yaml", "*.yml"):
            for entry in sorted(cache_dir.rglob(pattern)):
                rel = entry.relative_to(cache_dir).with_suffix("").as_posix()
                self._index[rel] = entry

    def _walk(self, dir_path: Path) -> None:
        for entry in sorted(dir_path.rglob("*")):
            if not entry.is_file():
                continue
            if entry.suffix not in (".yaml", ".yml"):
                continue

            # Key is the relative path inside the registry dir, without extension
            rel = entry.relative_to(dir_path).with_suffix("").as_posix()
            # Normalize key: lowercase the first segment (manufacturer)
            # but keep the rest
            parts = rel.split("/")
            if parts:
                parts[0] = parts[0].lower()
            key = "/".join(parts)
            self._index[key] = entry

    # ------------------------------------------------------------------
    # Lazy loading
    # ------------------------------------------------------------------

    def _load_schema(self, path: Path) -> InstrumentSchema:
        content = path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        return InstrumentSchema.model_validate(data)

    def get_schema(self, key: str) -> InstrumentSchema:
        """Load and cache a schema by its registry key.

        Thread-safe: lookups and mutations of ``_index`` / ``_cache`` are
        serialized by ``self._lock``. Blocking disk and network I/O happen
        outside the lock so that one slow fetch does not stall every other
        reader. Two concurrent callers fetching the same uncached key may
        both perform the I/O; the cache write uses :meth:`dict.setdefault`
        so that all callers end up returning the same cached instance.
        """
        # Fast path: cache hit / known on-disk path
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
            path = self._index.get(key)

        if path is not None:
            # Disk I/O outside the lock.
            schema = self._load_schema(path)
            with self._lock:
                return self._cache.setdefault(key, schema)

        # Not indexed locally — fall back to the remote client.
        if self._client is None:
            raise KeyError(f"Instrument '{key}' not found in registry.")

        parts = key.split("/")
        if len(parts) == 3:
            vendor, type_, model = parts
        elif len(parts) == 2:
            raise KeyError(
                f"Instrument key '{key}' is ambiguous. Expected format: vendor/type/model"
            )
        else:
            raise KeyError(
                f"Instrument '{key}' not found in registry. "
                f"Expected format: vendor/type/model"
            )

        # Network I/O outside the lock.
        schema = self._client.get_schema(vendor, type_, model)
        new_path = (
            self._client.cache_dir / vendor.lower() / type_.lower() / f"{model}.yaml"
        )

        with self._lock:
            self._index.setdefault(key, new_path)
            return self._cache.setdefault(key, schema)

    def try_get_schema(self, key: str) -> InstrumentSchema | None:
        """Load a schema if it exists, otherwise return None."""
        try:
            return self.get_schema(key)
        except KeyError:
            return None

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_instruments(self) -> list[str]:
        """Return all instrument keys in sorted order."""
        with self._lock:
            keys = list(self._index.keys())
        return sorted(keys)

    def search_instruments(
        self,
        manufacturer: str | None = None,
        keyword: str | None = None,
        category: str | None = None,
    ) -> list[str]:
        """Search instrument keys by manufacturer prefix, category, or keyword substring.

        Filters are AND-combined: an instrument must match every filter
        that is supplied. The ``category`` filter is matched against the
        second segment of the registry key (``vendor/<category>/model``),
        which is the convention enforced by :meth:`_walk` and the remote
        registry layout. Matching the key path keeps the search O(n)
        over the index and avoids triggering YAML parsing for every
        candidate.

        Results are sorted lexicographically.
        """
        results: list[str] = []
        mfr_lower = manufacturer.lower() if manufacturer else None
        kw_lower = keyword.lower() if keyword else None
        cat_lower = category.lower() if category else None

        # Snapshot under the lock so a concurrent insert into ``_index`` can't
        # mutate it mid-iteration ("dictionary changed size during iteration").
        with self._lock:
            keys = list(self._index.keys())

        for key in keys:
            parts = key.split("/")
            if mfr_lower is not None:
                # First segment is the manufacturer
                first_segment = parts[0] if parts else ""
                if mfr_lower not in first_segment:
                    continue
            if cat_lower is not None:
                # Second segment is the category (vendor/<category>/model)
                if len(parts) < 2 or cat_lower not in parts[1].lower():
                    continue
            if kw_lower is not None:
                if kw_lower not in key.lower():
                    continue
            results.append(key)

        return sorted(results)

    def get_metadata(self, key: str) -> dict[str, str] | None:
        """Return lightweight metadata for a key without fully parsing YAML.

        Falls back to full parsing if a quick peek fails.
        """
        with self._lock:
            path = self._index.get(key)
        if path is None:
            return None

        # Fast path: read first ~60 lines and look for instrument block.
        # This avoids the cost of full Pydantic validation when we only need
        # three string fields.  The heuristic is intentionally simple but
        # must tolerate common YAML formatting variations (quoted strings,
        # folded scalars, extra spaces).
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            meta: dict[str, str] = {}
            in_instrument = False
            for line in lines[:60]:
                stripped = line.strip()
                if stripped == "instrument:":
                    in_instrument = True
                    continue
                if in_instrument:
                    # Detect leaving the instrument block by seeing a top-level
                    # key that is not indented.
                    if stripped and not stripped.startswith(" ") and not stripped.startswith("-"):
                        break
                    # Use a simple regex-like split that tolerates extra spaces
                    # around the colon and strips YAML quoting characters.
                    if stripped.startswith("manufacturer:"):
                        meta["manufacturer"] = _strip_yaml_value(stripped)
                    elif stripped.startswith("model:"):
                        meta["model"] = _strip_yaml_value(stripped)
                    elif stripped.startswith("description:"):
                        meta["description"] = _strip_yaml_value(stripped)
            if "manufacturer" in meta and "model" in meta:
                logger.debug("get_metadata fast path hit for %s", key)
                return meta
            logger.debug("get_metadata fast path incomplete for %s (missing fields)", key)
        except Exception as exc:
            logger.debug("get_metadata fast path failed for %s: %s", key, exc)

        # Fallback: full parse.
        logger.debug("get_metadata falling back to full parse for %s", key)
        try:
            schema = self.get_schema(key)
            return {
                "manufacturer": schema.instrument.manufacturer,
                "model": schema.instrument.model,
                "description": schema.instrument.description or "",
            }
        except Exception as exc:
            logger.warning("get_metadata full parse failed for %s: %s", key, exc)
            return None

    def __len__(self) -> int:
        with self._lock:
            return len(self._index)

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._index

    def find_schema_by_idn(self, idn_info) -> str | None:
        """Find the best-matching schema key from parsed IDN info.

        Matching strategy (in order of priority):
        1. Exact manufacturer + exact model match
        2. Manufacturer match + model prefix/series match
           (e.g. model "2602B" should match schema for series "2600")
        3. Fuzzy manufacturer match + model match

        Args:
            idn_info: Parsed IDN information (manufacturer, model, etc.).

        Returns:
            The schema key (e.g. "keithley/smu/2600") or None if no match.
        """
        # Import here to avoid circular imports at module load time.
        from .idn_parser import IDNInfo

        if not isinstance(idn_info, IDNInfo):
            raise TypeError("idn_info must be an IDNInfo instance")

        idn_mfr = idn_info.manufacturer.lower().strip()
        idn_model = idn_info.model.strip()

        if not idn_mfr or not idn_model:
            return None

        # Snapshot under the lock for thread safety.
        with self._lock:
            keys = list(self._index.keys())

        def _series_prefix_match(idn_model: str, schema_model: str) -> bool:
            """Check if two models share a common numeric series prefix.

            Examples:
                - "2602B" and "2600" share "260" -> True
                - "DSOX1204G" and "DSOX1204G" share full string -> True
            """
            idn_numeric = re.match(r"^(\d+)", idn_model)
            schema_numeric = re.match(r"^(\d+)", schema_model)

            if idn_numeric and schema_numeric:
                idn_num = idn_numeric.group(1)
                schema_num = schema_numeric.group(1)
                min_len = min(len(idn_num), len(schema_num))
                for i in range(min_len, 2, -1):
                    if idn_num[:i] == schema_num[:i]:
                        return True
                return False

            return idn_model.startswith(schema_model) or schema_model.startswith(idn_model)

        best_match: str | None = None
        best_score = 0  # Higher is better

        for key in keys:
            meta = self.get_metadata(key)
            if meta is None:
                continue

            mfr = meta.get("manufacturer", "").lower().strip()
            model = meta.get("model", "").strip()

            if not mfr or not model:
                continue

            # --- Manufacturer matching ---
            mfr_score = 0
            if idn_mfr == mfr:
                mfr_score = 3  # Exact match
            elif idn_mfr in mfr or mfr in idn_mfr:
                mfr_score = 2  # Partial / substring match
            else:
                # Fuzzy: check word overlap
                idn_words = set(idn_mfr.split())
                mfr_words = set(mfr.split())
                if idn_words & mfr_words:
                    mfr_score = 1

            if mfr_score == 0:
                continue

            # --- Model matching ---
            model_score = 0
            if idn_model == model:
                model_score = 3  # Exact match
            elif _series_prefix_match(idn_model, model):
                model_score = 2  # Series/prefix match
            elif model.startswith(idn_model):
                model_score = 1  # Reverse prefix

            if model_score == 0:
                continue

            # Combined score: weight manufacturer slightly higher than model
            score = mfr_score * 10 + model_score

            # Prefer higher scores; on tie, prefer shorter keys (more specific).
            if score > best_score or (
                score == best_score
                and (best_match is None or len(key) < len(best_match))
            ):
                best_score = score
                best_match = key

        return best_match


class ValidationResult:
    """Result of validating a command against a schema."""

    def __init__(self, valid: bool, issues: list[str], suggestions: list[str]) -> None:
        self.valid = valid
        self.issues = issues
        self.suggestions = suggestions

    @classmethod
    def ok(cls) -> ValidationResult:
        return cls(True, [], [])

    @classmethod
    def fail(cls, issues: list[str], suggestions: list[str]) -> ValidationResult:
        return cls(False, issues, suggestions)


def validate_command(
    schema: InstrumentSchema,
    command: str,
    argument: str | None,
    current_state: dict[str, str],
) -> ValidationResult:
    """Validate a SCPI command + proposed argument against the instrument schema.

    Args:
        schema: The instrument schema to validate against.
        command: The SCPI command string (e.g. ":SOUR:VOLT").
        argument: The value the AI wants to set (e.g. "20" or "ON").
        current_state: A map of currently-set state (e.g. {"output": "ON", "source_mode": "VOLT"}).
    """
    issues: list[str] = []
    suggestions: list[str] = []

    logger.debug(
        "validate_command: instrument=%s command=%s argument=%s state=%s",
        schema.instrument.model,
        command,
        argument,
        current_state,
    )

    cmd_def = next((c for c in schema.commands if c.command == command), None)

    if cmd_def is None:
        issues.append(f"Unknown command '{command}'. Not found in instrument schema.")
        known = [c.command for c in schema.commands]
        suggestions.append(f"Available commands: {', '.join(known)}")
        logger.debug("validate_command: unknown command %s", command)
        return ValidationResult.fail(issues, suggestions)

    check_requires(cmd_def, current_state, issues, suggestions)
    check_forbidden_when(cmd_def, current_state, issues, suggestions)
    check_sequence_rules(cmd_def, command, argument, current_state, issues, suggestions)

    if argument is not None:
        check_argument(cmd_def, argument, issues, suggestions)

        if cmd_def.range is not None:
            try:
                val = float(argument)
                if val < cmd_def.range.min or val > cmd_def.range.max:
                    issues.append(
                        f"Value {val} for {command} is out of range "
                        f"[{cmd_def.range.min}, {cmd_def.range.max}]."
                    )
                    suggestions.append(
                        f"Use a value between {cmd_def.range.min} and "
                        f"{cmd_def.range.max} for {command}."
                    )
                check_global_limits(schema, command, val, issues, suggestions)
            except ValueError:
                pass  # not a number, range check skipped

    if cmd_def.safety is not None and cmd_def.safety.compliance_required:
        compl_param = cmd_def.safety.compliance_parameter
        if compl_param is None:
            # Surface the schema bug instead of silently checking a key that
            # cannot exist ("compliance"). Following the "fail loud, never
            # silent" principle from AGENTS.md §2.3.
            issues.append(
                f"Schema bug: {command} declares compliance_required=true "
                "but no compliance_parameter; cannot verify compliance."
            )
            suggestions.append(
                "Schema author should set safety.compliance_parameter to the "
                "SCPI command whose presence in state proves compliance is set."
            )
        elif compl_param not in current_state:
            issues.append(
                f"Safety: {command} requires compliance ({compl_param}) to be set before use."
            )
            suggestions.append(f"Set compliance first: {compl_param} <value>")

    if not issues:
        logger.debug("validate_command: %s PASS", command)
        return ValidationResult.ok()
    logger.debug("validate_command: %s FAIL issues=%s", command, issues)
    return ValidationResult.fail(issues, suggestions)


def check_requires(
    cmd_def: CommandDef,
    current_state: dict[str, str],
    issues: list[str],
    suggestions: list[str],
) -> None:
    for key, expected in cmd_def.requires.items():
        actual = current_state.get(key)
        if actual == expected:
            continue
        if actual is not None:
            issues.append(
                f"Requirement not met: {cmd_def.command} requires {key}={expected}, "
                f"but current state is {key}={actual}."
            )
        else:
            issues.append(
                f"Requirement not met: {cmd_def.command} requires {key}={expected}, "
                "but state is unknown."
            )
        suggestions.append(f"Set {key}={expected} before running {cmd_def.command}.")


def check_forbidden_when(
    cmd_def: CommandDef,
    current_state: dict[str, str],
    issues: list[str],
    suggestions: list[str],
) -> None:
    for key, forbidden_val in cmd_def.forbidden_when.items():
        actual = current_state.get(key)
        if actual == forbidden_val:
            issues.append(
                f"Forbidden: {cmd_def.command} cannot be executed when {key}={forbidden_val}."
            )
            # Generic suggestion: the schema does not declare which value is
            # "safe", so just tell the caller to change away from the forbidden
            # one. This avoids the old ON/OFF binary assumption that was wrong
            # for multi-valued states like trigger_source: EXT/INT/BUS.
            suggestions.append(
                f"Ensure {key} is not {forbidden_val} before running {cmd_def.command}."
            )


def _arg_matches_allowed(arg: str, allowed_values: list) -> bool:
    """Check if ``arg`` matches any value in ``allowed_values``.

    Handles the common case where YAML parses numeric literals as int/float
    while the incoming argument is still a string.
    """
    if arg in allowed_values:
        return True

    for val in allowed_values:
        # Handle bool separately since ``bool`` is a subclass of ``int``.
        if isinstance(val, bool):
            if arg.lower() in ("true", "1", "yes", "on") and val is True:
                return True
            if arg.lower() in ("false", "0", "no", "off") and val is False:
                return True
        elif isinstance(val, int):
            try:
                if int(arg) == val:
                    return True
            except ValueError:
                continue
        elif isinstance(val, float):
            try:
                if float(arg) == val:
                    return True
            except ValueError:
                continue

    return False


def check_argument(
    cmd_def: CommandDef,
    arg: str,
    issues: list[str],
    suggestions: list[str],
) -> None:
    """Validate ``arg`` against the command's ``parameters.allowed_values``.

    For single-parameter commands the whole argument is matched against
    the first parameter. For multi-parameter commands (e.g.
    ``:CONF:TEMP TC,J,1``) the argument is split on commas and each
    part is matched positionally against the corresponding parameter.
    """
    parts = [p.strip() for p in arg.split(",")]
    for i, param in enumerate(cmd_def.parameters):
        if i >= len(parts):
            break
        if not param.allowed_values:
            continue
        if not _arg_matches_allowed(parts[i], param.allowed_values):
            issues.append(
                f"Invalid value '{parts[i]}' for parameter '{param.name}'. "
                f"Allowed: {param.allowed_values}."
            )
            suggestions.append(f"Use one of {param.allowed_values} for parameter '{param.name}'.")


def check_global_limits(
    schema: InstrumentSchema,
    command: str,
    value: float,
    issues: list[str],
    suggestions: list[str],
) -> None:
    cmd_upper = command.upper()
    limits = schema.global_limits
    if "VOLT" in cmd_upper and limits.voltage is not None and abs(value) > limits.voltage.max:
        issues.append(
            f"Global limit: {command} value {value} exceeds voltage max {limits.voltage.max}."
        )
        suggestions.append(f"Reduce voltage to <= {limits.voltage.max} {limits.voltage.unit}.")
    if "CURR" in cmd_upper and limits.current is not None and abs(value) > limits.current.max:
        issues.append(
            f"Global limit: {command} value {value} exceeds current max {limits.current.max}."
        )
        suggestions.append(f"Reduce current to <= {limits.current.max} {limits.current.unit}.")
    if "FREQ" in cmd_upper and limits.frequency is not None and abs(value) > limits.frequency.max:
        issues.append(
            f"Global limit: {command} value {value} exceeds frequency max {limits.frequency.max}."
        )
        suggestions.append(f"Reduce frequency to <= {limits.frequency.max} {limits.frequency.unit}.")


def _check_sequence_rule(rule: SequenceRule, current_state: dict[str, str]) -> bool:
    """Pure rule interpreter — zero instrument knowledge.

    Evaluates the four primitives: key existence, key-value match,
    numeric range, and set membership.  All semantics are declared in
    the YAML schema; the engine only executes Boolean matching.
    """
    if rule.require_state_keys_present:
        if not any(k in current_state for k in rule.require_state_keys_present):
            return False
    if rule.expect_state:
        if not all(current_state.get(k) == v for k, v in rule.expect_state.items()):
            return False
    return True


def check_sequence_rules(
    cmd_def: CommandDef,
    command: str,
    argument: str | None,
    current_state: dict[str, str],
    issues: list[str],
    suggestions: list[str],
) -> None:
    """Validate sequence ``before`` rules for a command.

    Rules with ``before`` are evaluated when the command (or command+argument)
    matches the rule's ``before`` value. Rules with ``after`` are skipped here;
    they are checked after the command has been executed (e.g. in sequence
    validation once state has been updated).
    """
    if cmd_def.safety is None:
        return
    full_cmd = f"{command} {argument}".strip() if argument else command
    for rule in cmd_def.safety.sequence:
        if rule.before is not None:
            if rule.before != command and rule.before != full_cmd:
                continue
        elif rule.after is not None:
            # After rules are validated post-execution in sequence validation.
            continue
        else:
            # Rule has neither before nor after — apply to all invocations.
            pass

        if not _check_sequence_rule(rule, current_state):
            issues.append(f"Sequence safety: {rule.message}")
            suggestions.append("Check state requirements before this command.")


def check_sequence_rules_after(
    cmd_def: CommandDef,
    command: str,
    argument: str | None,
    current_state: dict[str, str],
    issues: list[str],
    suggestions: list[str],
) -> None:
    """Validate sequence ``after`` rules for a command.

    Call this after the command has been "executed" and ``current_state`` has
    been updated to reflect the new state.
    """
    if cmd_def.safety is None:
        return
    full_cmd = f"{command} {argument}".strip() if argument else command
    for rule in cmd_def.safety.sequence:
        if rule.after is None:
            continue
        if rule.after != command and rule.after != full_cmd:
            continue

        if not _check_sequence_rule(rule, current_state):
            issues.append(f"Sequence safety: {rule.message}")
            suggestions.append("Check state requirements after this command.")
