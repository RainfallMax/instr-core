"""Tests for the PyVISA compatibility service."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from instr_core.api.services import visa_service


def test_get_visa_does_not_reuse_manager_on_source_id_collision() -> None:
    """A recycled object ID must not select a stale ResourceManager."""
    stale_manager = object()
    new_manager = object()
    new_source = MagicMock()
    new_source.ResourceManager.return_value = new_manager

    visa_service._rm = stale_manager
    visa_service._rm_source = MagicMock()

    with patch("instr_core.api_server.pyvisa", new_source):
        assert visa_service.get_visa() is new_manager
