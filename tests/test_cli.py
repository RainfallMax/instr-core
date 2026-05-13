"""Tests for the instr-core CLI surface in ``instr_core.main``.

These tests exercise argument parsing and signal handling in isolation
from the actual server runtime, so they neither open the MCP transport
nor touch the on-disk registry.
"""

from __future__ import annotations

import logging
import signal

import pytest

from instr_core import __version__
from instr_core.main import _build_parser, _install_signal_handlers


class TestVersionFlag:
    def test_version_flag_prints_version_and_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        parser = _build_parser()
        with pytest.raises(SystemExit) as excinfo:
            parser.parse_args(["--version"])
        assert excinfo.value.code == 0
        captured = capsys.readouterr()
        # argparse writes ``--version`` output to stdout in Python 3.10+,
        # but historically used stderr; accept either to stay portable.
        out = captured.out or captured.err
        assert f"instr-core {__version__}" in out


class TestLogLevelFlag:
    def test_default_log_level_is_info(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("INSTR_CORE_LOG_LEVEL", raising=False)
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.log_level == "INFO"

    def test_log_level_explicit_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("INSTR_CORE_LOG_LEVEL", raising=False)
        parser = _build_parser()
        args = parser.parse_args(["--log-level", "WARNING"])
        assert args.log_level == "WARNING"

    def test_log_level_is_uppercased(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Lower-case input on the CLI must be normalized to upper-case so
        that ``getattr(logging, args.log_level)`` succeeds."""
        monkeypatch.delenv("INSTR_CORE_LOG_LEVEL", raising=False)
        parser = _build_parser()
        args = parser.parse_args(["--log-level", "debug"])
        assert args.log_level == "DEBUG"

    def test_invalid_log_level_exits_with_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("INSTR_CORE_LOG_LEVEL", raising=False)
        parser = _build_parser()
        with pytest.raises(SystemExit) as excinfo:
            parser.parse_args(["--log-level", "TRACE"])
        # argparse exits with status 2 on invalid arguments.
        assert excinfo.value.code != 0

    def test_env_var_supplies_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When no --log-level is given on the CLI, the value of
        ``INSTR_CORE_LOG_LEVEL`` should be used (and uppercased)."""
        monkeypatch.setenv("INSTR_CORE_LOG_LEVEL", "warning")
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.log_level == "WARNING"

    def test_cli_value_overrides_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("INSTR_CORE_LOG_LEVEL", "WARNING")
        parser = _build_parser()
        args = parser.parse_args(["--log-level", "DEBUG"])
        assert args.log_level == "DEBUG"


class TestSignalHandlers:
    @pytest.fixture(autouse=True)
    def _restore_handlers(self):
        """Snapshot and restore SIGINT/SIGTERM so these tests don't leak
        the test-runner's signal state."""
        original_sigint = signal.getsignal(signal.SIGINT)
        original_sigterm = signal.getsignal(signal.SIGTERM)
        try:
            yield
        finally:
            signal.signal(signal.SIGINT, original_sigint)
            signal.signal(signal.SIGTERM, original_sigterm)

    def test_install_signal_handlers_registers_sigint_and_sigterm(self) -> None:
        _install_signal_handlers()
        # The handler is an inner function inside _install_signal_handlers,
        # so we can't compare identity directly; what we can confirm is
        # that the handler was changed away from the default and that the
        # SIGINT/SIGTERM handlers are now the *same* callable.
        sigint_handler = signal.getsignal(signal.SIGINT)
        sigterm_handler = signal.getsignal(signal.SIGTERM)
        assert callable(sigint_handler)
        assert callable(sigterm_handler)
        assert sigint_handler is sigterm_handler
        # And it isn't one of Python's well-known defaults.
        assert sigint_handler not in (signal.SIG_DFL, signal.SIG_IGN)

    def test_signal_handler_logs_and_exits_zero(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        _install_signal_handlers()
        handler = signal.getsignal(signal.SIGINT)
        assert callable(handler)

        with caplog.at_level(logging.INFO, logger="root"):
            with pytest.raises(SystemExit) as excinfo:
                handler(signal.SIGINT, None)  # type: ignore[misc]

        assert excinfo.value.code == 0
        assert any(
            "Received SIGINT" in record.getMessage() and "shutting down" in record.getMessage()
            for record in caplog.records
        )
