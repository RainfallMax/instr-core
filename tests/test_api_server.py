"""Tests for the FastAPI HTTP server (api_server.py).

These tests use TestClient and mock PyVISA so they run without real hardware.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from instr_core.api_server import create_api_app
from instr_core.validator import Registry

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "registry"


# ---------------------------------------------------------------------------
# PyVISA mocks
# ---------------------------------------------------------------------------


class MockResource:
    """Mock PyVISA resource for testing."""

    def __init__(self, idn_response: str = "KEITHLEY,MODEL 2602B,123,1.0") -> None:
        self._idn = idn_response
        self._written: list[str] = []

    def query(self, cmd: str) -> str:
        if cmd == "*IDN?":
            return self._idn
        return "0"

    def write(self, cmd: str) -> None:
        self._written.append(cmd)


class MockResourceManager:
    """Mock PyVISA ResourceManager for testing."""

    def __init__(self, idn_response: str = "KEITHLEY,MODEL 2602B,123,1.0") -> None:
        self._idn = idn_response

    def list_resources(self) -> tuple[str, ...]:
        return ("USB0::0x05E6::0x2600::INSTR",)

    def open_resource(self, address: str) -> MockResource:
        return MockResource(self._idn)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> Registry:
    return Registry.load(FIXTURES_ROOT)


@pytest.fixture
def client(registry: Registry) -> TestClient:
    import threading
    from instr_core.sweep import SweepEngine

    app = create_api_app()
    # Manually init app.state since lifespan does not run in bare TestClient()
    app.state.registry = registry
    app.state.sweep_engine = SweepEngine()
    app.state.address_lock = threading.RLock()
    app.state.address_to_schema = {}
    app.state.address_state = {}
    return TestClient(app)


# ---------------------------------------------------------------------------
# Health & Registry endpoints
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health_returns_ok(self, client: TestClient) -> None:
        res = client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["registry_count"] == 2


class TestListInstruments:
    def test_lists_fixture_schemas(self, client: TestClient) -> None:
        res = client.get("/instruments")
        assert res.status_code == 200
        data = res.json()
        keys = {item["key"] for item in data}
        assert "keithley/smu/2600" in keys
        assert "keysight/scope/dsox1204g" in keys


class TestGetInstrument:
    def test_get_existing_schema(self, client: TestClient) -> None:
        res = client.get("/instruments/keithley/smu/2600")
        assert res.status_code == 200
        data = res.json()
        assert data["key"] == "keithley/smu/2600"
        assert data["schema"]["instrument"]["manufacturer"] == "Keithley"

    def test_get_unknown_returns_404(self, client: TestClient) -> None:
        res = client.get("/instruments/unknown/type/model")
        assert res.status_code == 404


class TestSafetyLimits:
    def test_get_safety_limits(self, client: TestClient) -> None:
        res = client.get("/instruments/keithley/smu/2600/safety-limits")
        assert res.status_code == 200
        data = res.json()
        assert data["voltage"]["max"] == 40.0
        assert data["current"]["max"] == 3.0


# ---------------------------------------------------------------------------
# Validation endpoints (no hardware required)
# ---------------------------------------------------------------------------


class TestValidateCommand:
    def test_valid_command_by_schema_key(self, client: TestClient) -> None:
        res = client.post(
            "/validate/command",
            json={
                "instrument": "keithley/smu/2600",
                "command": ":SOUR:FUNC",
                "argument": "VOLT",
                "current_state": {"output": "OFF"},
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["valid"] is True
        assert data["command"] == ":SOUR:FUNC"
        assert data["argument"] == "VOLT"

    def test_invalid_command_out_of_range(self, client: TestClient) -> None:
        res = client.post(
            "/validate/command",
            json={
                "instrument": "keithley/smu/2600",
                "command": ":SOUR:VOLT",
                "argument": "50",
                "current_state": {"source_mode": "VOLT"},
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["valid"] is False
        assert any("out of range" in i.lower() for i in data["issues"])

    def test_auto_split_command_argument(self, client: TestClient) -> None:
        """When argument is not provided but command contains a space,
        the endpoint should auto-split."""
        res = client.post(
            "/validate/command",
            json={
                "instrument": "keithley/smu/2600",
                "command": ":SOUR:FUNC VOLT",
                "current_state": {"output": "OFF"},
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["command"] == ":SOUR:FUNC"
        assert data["argument"] == "VOLT"
        assert data["valid"] is True

    def test_unknown_instrument_returns_404(self, client: TestClient) -> None:
        res = client.post(
            "/validate/command",
            json={
                "instrument": "nonexistent/smu/9999",
                "command": ":SOUR:VOLT",
                "argument": "10",
            },
        )
        assert res.status_code == 404

    def test_no_schema_graceful_degradation(self, client: TestClient) -> None:
        """When no instrument or address is provided, return a soft pass
        with an informational issue."""
        res = client.post(
            "/validate/command",
            json={"command": ":SOUR:VOLT 10"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["valid"] is True
        assert any("No schema available" in i for i in data["issues"])

    def test_compliance_required_blocked(self, client: TestClient) -> None:
        """Enabling output without compliance should fail validation."""
        res = client.post(
            "/validate/command",
            json={
                "instrument": "keithley/smu/2600",
                "command": ":OUTP ON",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["valid"] is False
        assert any("Compliance must be configured" in i for i in data["issues"])


# ---------------------------------------------------------------------------
# PyVISA hardware layer (mocked)
# ---------------------------------------------------------------------------


class TestVisaConnect:
    @patch("instr_core.api_server.pyvisa")
    def test_connect_auto_discovers_schema(self, mock_pyvisa: MagicMock, client: TestClient) -> None:
        mock_pyvisa.ResourceManager.return_value = MockResourceManager(
            idn_response="KEITHLEY INSTRUMENTS INC.,MODEL 2602B,1398987,3.2.0"
        )

        res = client.post("/visa/connect", params={"address": "USB0::0x05E6::0x2600::INSTR"})
        assert res.status_code == 200
        data = res.json()
        assert data["address"] == "USB0::0x05E6::0x2600::INSTR"
        assert data["schema_key"] == "keithley/smu/2600"
        assert "2602B" in data["model"] or "KEITHLEY" in data["manufacturer"]

    @patch("instr_core.api_server.pyvisa")
    def test_connect_unknown_instrument_no_schema(self, mock_pyvisa: MagicMock, client: TestClient) -> None:
        mock_pyvisa.ResourceManager.return_value = MockResourceManager(
            idn_response="Unknown Corp,XYZ123,999,1.0"
        )

        res = client.post("/visa/connect", params={"address": "USB0::9999::INSTR"})
        assert res.status_code == 200
        data = res.json()
        assert data["schema_key"] is None

    @patch("instr_core.api_server.pyvisa")
    def test_connect_pyvisa_not_installed(self, mock_pyvisa: MagicMock, client: TestClient) -> None:
        mock_pyvisa.ResourceManager.side_effect = ImportError("No VISA library found")

        res = client.post("/visa/connect", params={"address": "USB0::INSTR"})
        assert res.status_code == 500


class TestVisaCommand:
    @patch("instr_core.api_server.pyvisa")
    def test_query_command_not_blocked_even_when_unknown(
        self, mock_pyvisa: MagicMock, client: TestClient
    ) -> None:
        """Query commands (*IDN? is not in any schema) must still be allowed
        to reach hardware — they are read-only."""
        mock_rm = MockResourceManager(idn_response="KEITHLEY,MODEL 2602B,123,1.0")
        mock_pyvisa.ResourceManager.return_value = mock_rm

        # First connect to establish schema mapping
        client.post("/visa/connect", params={"address": "USB0::INSTR"})

        res = client.post(
            "/visa/command",
            json={"address": "USB0::INSTR", "command": "*IDN?", "validate": True},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["validated"] is True
        assert data["error"] is None

    @patch("instr_core.api_server.pyvisa")
    def test_blocked_write_command_returns_error(self, mock_pyvisa: MagicMock, client: TestClient) -> None:
        mock_rm = MockResourceManager(idn_response="KEITHLEY,MODEL 2602B,123,1.0")
        mock_pyvisa.ResourceManager.return_value = mock_rm

        # Connect
        client.post("/visa/connect", params={"address": "USB0::INSTR"})

        # Try to enable output without compliance (should be blocked)
        res = client.post(
            "/visa/command",
            json={"address": "USB0::INSTR", "command": ":OUTP ON", "validate": True},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["validated"] is True
        assert data["error"] is not None
        assert "VALIDATION BLOCKED" in data["error"]
        assert any("Compliance must be configured" in i for i in data["validation_issues"])

    @patch("instr_core.api_server.pyvisa")
    def test_query_command_allowed_even_if_validation_fails(
        self, mock_pyvisa: MagicMock, client: TestClient
    ) -> None:
        """Queries should not be blocked by validation failures — they are
        read-only and cannot damage hardware."""
        mock_rm = MockResourceManager(idn_response="KEITHLEY,MODEL 2602B,123,1.0")
        mock_pyvisa.ResourceManager.return_value = mock_rm

        client.post("/visa/connect", params={"address": "USB0::INSTR"})

        # A query command ending with ? should always be allowed even if
        # the schema flags it (e.g. querying while output off).
        res = client.post(
            "/visa/command",
            json={"address": "USB0::INSTR", "command": ":MEAS:VOLT?", "validate": True},
        )
        assert res.status_code == 200
        data = res.json()
        # Should succeed (query commands are not blocked)
        assert data["error"] is None

    @patch("instr_core.api_server.pyvisa")
    def test_validation_skipped_when_no_schema(self, mock_pyvisa: MagicMock, client: TestClient) -> None:
        mock_rm = MockResourceManager(idn_response="Unknown Corp,XYZ123,999,1.0")
        mock_pyvisa.ResourceManager.return_value = mock_rm

        client.post("/visa/connect", params={"address": "USB0::INSTR"})

        res = client.post(
            "/visa/command",
            json={"address": "USB0::INSTR", "command": ":OUTP ON", "validate": True},
        )
        assert res.status_code == 200
        data = res.json()
        # No schema = no validation, command goes through
        assert data["validated"] is False
        assert data["error"] is None


class TestVisaResources:
    @patch("instr_core.api_server.pyvisa")
    def test_list_resources(self, mock_pyvisa: MagicMock, client: TestClient) -> None:
        mock_pyvisa.ResourceManager.return_value = MockResourceManager()

        res = client.get("/visa/resources")
        assert res.status_code == 200
        data = res.json()
        assert "USB0::0x05E6::0x2600::INSTR" in data
