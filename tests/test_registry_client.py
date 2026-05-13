"""Tests for RegistryClient remote fetch and local cache logic."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from instr_core.registry_client import RegistryClient
from instr_core.schema import InstrumentSchema

SAMPLE_YAML = """
instrument:
  manufacturer: Keithley
  model: "2400"
  description: "SourceMeter"

global_limits:
  voltage: {max: 200.0, unit: "V"}
  current: {max: 1.0, unit: "A"}
  power: {max: 20.0, unit: "W"}

commands:
  - command: ":OUTP"
    parameters:
      - name: state
        type: string
        allowed_values: ["ON", "OFF"]
"""


class TestRegistryClient:
    def test_cache_dir_property(self) -> None:
        custom = Path("/tmp/my-cache")
        client = RegistryClient(cache_dir=custom)
        assert client.cache_dir == custom

    def test_default_cache_dir(self) -> None:
        client = RegistryClient()
        expected = Path.home() / ".instr-core" / "registry_cache"
        assert client.cache_dir == expected

    def test_get_schema_from_cache(self, tmp_path: Path) -> None:
        cache = tmp_path / "registry_cache"
        cache_dir = cache / "keithley" / "smu"
        cache_dir.mkdir(parents=True)
        (cache_dir / "2400.yaml").write_text(SAMPLE_YAML, encoding="utf-8")

        client = RegistryClient(cache_dir=cache)
        schema = client.get_schema("keithley", "smu", "2400")

        assert isinstance(schema, InstrumentSchema)
        assert schema.instrument.manufacturer == "Keithley"
        assert schema.instrument.model == "2400"

    @patch("instr_core.registry_client.requests.get")
    def test_get_schema_from_remote(self, mock_get: MagicMock, tmp_path: Path) -> None:
        mock_response = MagicMock()
        mock_response.text = SAMPLE_YAML
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        cache = tmp_path / "registry_cache"
        client = RegistryClient(
            base_url="https://example.com/registry",
            cache_dir=cache,
        )
        schema = client.get_schema("keithley", "smu", "2400")

        assert isinstance(schema, InstrumentSchema)
        assert schema.instrument.model == "2400"
        mock_get.assert_called_once()

        # Verify cache was written
        cached_file = cache / "keithley" / "smu" / "2400.yaml"
        assert cached_file.exists()
        assert cached_file.read_text(encoding="utf-8") == SAMPLE_YAML

    @patch("instr_core.registry_client.requests.get")
    def test_get_schema_remote_failure(self, mock_get: MagicMock, tmp_path: Path) -> None:
        from requests import RequestException

        mock_get.side_effect = RequestException("network error")

        client = RegistryClient(cache_dir=tmp_path / "registry_cache")
        with pytest.raises(RuntimeError, match="Failed to fetch schema"):
            client.get_schema("keithley", "smu", "2400")
