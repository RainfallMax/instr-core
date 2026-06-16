"""Tests for the SCPI *IDN? parser and Registry IDN matching."""

from __future__ import annotations

from pathlib import Path

import pytest

from instr_core.idn_parser import IDNInfo, parse_idn
from instr_core.validator import Registry

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "registry"


class TestParseIDN:
    """Cover parse_idn with representative instrument *IDN? strings."""

    def test_keithley_2602b(self) -> None:
        idn = parse_idn("KEITHLEY INSTRUMENTS INC.,MODEL 2602B,1398987,3.2.0")
        assert idn.manufacturer == "keithley"
        assert idn.model == "2602B"
        assert idn.serial == "1398987"
        assert idn.firmware == "3.2.0"

    def test_keysight_dsox1204g(self) -> None:
        idn = parse_idn("Keysight Technologies,DSOX1204G,CN12345678,02.42.2020012900")
        assert idn.manufacturer == "keysight"
        assert idn.model == "DSOX1204G"
        assert idn.serial == "CN12345678"
        assert idn.firmware == "02.42.2020012900"

    def test_tektronix_mso56(self) -> None:
        idn = parse_idn("TEKTRONIX,MSO56,B010001,CF:91.1CT FV:1.0.0")
        assert idn.manufacturer == "tektronix"
        assert idn.model == "MSO56"
        assert idn.serial == "B010001"
        assert idn.firmware == "CF:91.1CT FV:1.0.0"

    def test_rohde_schwarz(self) -> None:
        idn = parse_idn("Rohde & Schwarz GmbH & Co. KG,ZVA40,99999,2.0")
        assert idn.manufacturer == "rohde & schwarz gmbh & co. kg"
        assert idn.model == "ZVA40"

    def test_short_idn_no_serial_firmware(self) -> None:
        idn = parse_idn("Acme,XYZ")
        assert idn.manufacturer == "acme"
        assert idn.model == "XYZ"
        assert idn.serial is None
        assert idn.firmware is None

    def test_empty_idn(self) -> None:
        idn = parse_idn("")
        assert idn.manufacturer == ""
        assert idn.model == ""
        assert idn.serial is None
        assert idn.firmware is None

    def test_idn_info_model_validation(self) -> None:
        info = IDNInfo(manufacturer="keithley", model="2600")
        assert info.manufacturer == "keithley"
        assert info.model == "2600"
        assert info.serial is None
        assert info.firmware is None


class TestRegistryFindSchemaByIDN:
    """Cover Registry.find_schema_by_idn with fixture schemas."""

    @pytest.fixture(scope="class")
    def registry(self) -> Registry:
        return Registry.load(FIXTURES_ROOT)

    def test_find_keithley_2602b(self, registry: Registry) -> None:
        idn = parse_idn("KEITHLEY INSTRUMENTS INC.,MODEL 2602B,1398987,3.2.0")
        key = registry.find_schema_by_idn(idn)
        assert key == "keithley/smu/2600"

    def test_find_keithley_2601b(self, registry: Registry) -> None:
        idn = parse_idn("KEITHLEY,MODEL 2601B,12345,1.0")
        key = registry.find_schema_by_idn(idn)
        assert key == "keithley/smu/2600"

    def test_find_keysight_dsox1204g_exact(self, registry: Registry) -> None:
        idn = parse_idn("Keysight Technologies,DSOX1204G,CN12345678,02.42.2020012900")
        key = registry.find_schema_by_idn(idn)
        assert key == "keysight/scope/dsox1204g"

    def test_find_unknown_returns_none(self, registry: Registry) -> None:
        idn = parse_idn("Unknown Corp,XYZ123,999,1.0")
        key = registry.find_schema_by_idn(idn)
        assert key is None

    def test_find_empty_idn_returns_none(self, registry: Registry) -> None:
        idn = IDNInfo(manufacturer="", model="")
        key = registry.find_schema_by_idn(idn)
        assert key is None

    def test_find_requires_idn_info_type(self, registry: Registry) -> None:
        with pytest.raises(TypeError):
            registry.find_schema_by_idn("not an IDNInfo")

    def test_find_is_thread_safe(self, registry: Registry) -> None:
        """Concurrent calls must not raise."""
        import threading

        idn = parse_idn("KEITHLEY INSTRUMENTS INC.,MODEL 2602B,1398987,3.2.0")
        errors: list[BaseException] = []

        def worker() -> None:
            try:
                for _ in range(50):
                    registry.find_schema_by_idn(idn)
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"find_schema_by_idn raised: {errors!r}"
