"""Tests for the FastAPI HTTP server (api_server.py).

These tests use TestClient and mock PyVISA so they run without real hardware.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from instr_core.api.services.ownership_service import AddressOwnershipRegistry
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


class EmergencyResource(MockResource):
    """Resource that can fail every emergency write."""

    def __init__(self, fail_writes: bool = False) -> None:
        super().__init__()
        self.fail_writes = fail_writes

    def write(self, cmd: str) -> None:
        self._written.append(cmd)
        if self.fail_writes:
            raise RuntimeError("emergency write failed")


class EmergencyResourceManager:
    """Addressable resources for global emergency-stop tests."""

    def __init__(self, resources: dict[str, EmergencyResource]) -> None:
        self.resources = resources
        self.opened: list[str] = []

    def open_resource(self, address: str) -> EmergencyResource:
        self.opened.append(address)
        return self.resources[address]


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

    def test_no_schema_fails_closed(self, client: TestClient) -> None:
        res = client.post(
            "/validate/command",
            json={"command": ":SOUR:VOLT 10"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["valid"] is False
        assert any("No schema available" in issue for issue in data["issues"])
        assert any(
            "provide explicit instrument" in item.lower()
            for item in data["suggestions"]
        )

    def test_address_resolves_connected_schema(self, client: TestClient) -> None:
        client.app.state.address_to_schema["USB0::KNOWN::INSTR"] = "keithley/smu/2600"
        res = client.post(
            "/validate/command",
            json={
                "address": "USB0::KNOWN::INSTR",
                "command": ":SOUR:FUNC VOLT",
                "current_state": {"output": "OFF"},
            },
        )
        assert res.status_code == 200
        assert res.json()["valid"] is True
        assert res.json()["instrument"] == "keithley/smu/2600"

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
    @patch("instr_core.api.routes.visa.get_visa")
    def test_unknown_schema_write_is_rejected_before_visa(
        self, mock_get_visa: MagicMock, client: TestClient
    ) -> None:
        client.app.state.address_to_schema["USB0::UNKNOWN::INSTR"] = None
        res = client.post(
            "/visa/command",
            json={
                "address": "USB0::UNKNOWN::INSTR",
                "command": ":OUTP ON",
                "validate": True,
            },
        )
        assert res.status_code == 422
        assert "schema" in res.json()["detail"].lower()
        mock_get_visa.assert_not_called()

    @patch("instr_core.api.routes.visa.get_visa")
    def test_hardware_write_cannot_disable_validation(
        self, mock_get_visa: MagicMock, client: TestClient
    ) -> None:
        client.app.state.address_to_schema["USB0::KNOWN::INSTR"] = "keithley/smu/2600"
        res = client.post(
            "/visa/command",
            json={
                "address": "USB0::KNOWN::INSTR",
                "command": ":SOUR:VOLT 1",
                "validate": False,
            },
        )
        assert res.status_code == 422
        assert "validation" in res.json()["detail"].lower()
        mock_get_visa.assert_not_called()

    @patch("instr_core.api_server.pyvisa")
    def test_idn_query_is_allowed_without_schema(
        self, mock_pyvisa: MagicMock, client: TestClient
    ) -> None:
        mock_pyvisa.ResourceManager.return_value = MockResourceManager(
            idn_response="Unknown Corp,XYZ123,999,1.0"
        )
        client.app.state.address_to_schema["USB0::UNKNOWN::INSTR"] = None
        res = client.post(
            "/visa/command",
            json={
                "address": "USB0::UNKNOWN::INSTR",
                "command": "*IDN?",
                "validate": True,
            },
        )
        assert res.status_code == 200
        assert res.json()["response"] == "Unknown Corp,XYZ123,999,1.0"

    @patch("instr_core.api.routes.visa.get_visa")
    def test_unknown_query_is_rejected_before_visa(
        self, mock_get_visa: MagicMock, client: TestClient
    ) -> None:
        client.app.state.address_to_schema["USB0::UNKNOWN::INSTR"] = None
        res = client.post(
            "/visa/command",
            json={
                "address": "USB0::UNKNOWN::INSTR",
                "command": ":READ?",
                "validate": True,
            },
        )
        assert res.status_code == 422
        mock_get_visa.assert_not_called()

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
        assert data["validated"] is False
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
        assert res.status_code == 422
        assert "validation" in res.json()["detail"].lower()

    @patch("instr_core.api_server.pyvisa")
    def test_query_command_is_blocked_when_validation_fails(
        self, mock_pyvisa: MagicMock, client: TestClient
    ) -> None:
        mock_rm = MockResourceManager(idn_response="KEITHLEY,MODEL 2602B,123,1.0")
        mock_pyvisa.ResourceManager.return_value = mock_rm

        client.post("/visa/connect", params={"address": "USB0::INSTR"})

        res = client.post(
            "/visa/command",
            json={"address": "USB0::INSTR", "command": ":MEAS:VOLT?", "validate": True},
        )
        assert res.status_code == 422


class TestVisaResources:
    @patch("instr_core.api_server.pyvisa")
    def test_list_resources(self, mock_pyvisa: MagicMock, client: TestClient) -> None:
        mock_pyvisa.ResourceManager.return_value = MockResourceManager()

        res = client.get("/visa/resources")
        assert res.status_code == 200
        data = res.json()
        assert "USB0::0x05E6::0x2600::INSTR" in data


class TestSweepOwnership:
    @patch("instr_core.api.services.visa_service.get_visa")
    def test_owned_address_rejects_sweep_before_visa(
        self, mock_get_visa: MagicMock, client: TestClient
    ) -> None:
        address = "USB0::KNOWN::INSTR"
        client.app.state.address_to_schema[address] = "keithley/smu/2600"
        ownership = AddressOwnershipRegistry()
        ownership.acquire(address, "existing-run")
        client.app.state.address_ownership = ownership

        res = client.post(
            "/sweep/start",
            json={
                "instrument_key": "keithley/smu/2600",
                "address": address,
                "config": {
                    "start_voltage": 0,
                    "stop_voltage": 1,
                    "step": 0.5,
                    "compliance": 0.01,
                    "delay_ms": 0,
                    "direction": "UP",
                },
            },
        )

        assert res.status_code == 409
        mock_get_visa.assert_not_called()


class TestEmergencyStop:
    @patch("instr_core.api_server.pyvisa")
    def test_emergency_stop_attempts_every_owned_address(
        self, mock_pyvisa: MagicMock, client: TestClient
    ) -> None:
        resources = {
            "USB0::1": EmergencyResource(),
            "USB0::2": EmergencyResource(),
        }
        rm = EmergencyResourceManager(resources)
        mock_pyvisa.ResourceManager.return_value = rm
        ownership = AddressOwnershipRegistry()
        ownership.acquire("USB0::1", "run-1")
        ownership.acquire("USB0::2", "run-2")
        client.app.state.address_ownership = ownership

        res = client.post("/visa/emergency-stop")

        assert res.status_code == 200
        data = res.json()
        assert data["all_safe"] is True
        assert {item["address"] for item in data["results"]} == {
            "USB0::1",
            "USB0::2",
        }
        assert rm.opened == ["USB0::1", "USB0::2"]
        assert ownership.snapshot() == {}

    @patch("instr_core.api_server.pyvisa")
    def test_emergency_stop_continues_after_partial_failure(
        self, mock_pyvisa: MagicMock, client: TestClient
    ) -> None:
        resources = {
            "USB0::FAIL": EmergencyResource(fail_writes=True),
            "USB0::SAFE": EmergencyResource(),
        }
        mock_pyvisa.ResourceManager.return_value = EmergencyResourceManager(resources)
        ownership = AddressOwnershipRegistry()
        ownership.acquire("USB0::FAIL", "run-fail")
        ownership.acquire("USB0::SAFE", "run-safe")
        client.app.state.address_ownership = ownership

        res = client.post("/visa/emergency-stop")

        assert res.status_code == 200
        data = res.json()
        assert data["all_safe"] is False
        by_address = {item["address"]: item for item in data["results"]}
        assert by_address["USB0::FAIL"]["attempted_commands"] == [
            ":OUTP OFF",
            ":OUTP OFF",
            "*RST",
        ]
        assert by_address["USB0::SAFE"]["safe"] is True
        assert ownership.snapshot() == {"USB0::FAIL": "run-fail"}
