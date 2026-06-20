"""Tests for managed VISA resource sessions."""

from __future__ import annotations

import threading
import time

import pytest

from instr_core.api.models import ConnectedInstrument
from instr_core.api.services.session_manager import (
    SessionConnectError,
    SessionNotFound,
    SessionUnhealthy,
    VisaSessionManager,
)


class FakeResource:
    def __init__(self, name: str) -> None:
        self.name = name
        self.closed = 0
        self.commands: list[str] = []
        self.fail_write = False

    def write(self, command: str) -> None:
        self.commands.append(command)
        if self.fail_write:
            raise RuntimeError("write failed")

    def close(self) -> None:
        self.closed += 1


class FakeResourceManager:
    def __init__(self) -> None:
        self.resources: list[FakeResource] = []
        self.closed = 0

    def open_resource(self, address: str) -> FakeResource:
        resource = FakeResource(f"{address}-{len(self.resources)}")
        self.resources.append(resource)
        return resource

    def close(self) -> None:
        self.closed += 1


def identify(address: str, resource: FakeResource) -> ConnectedInstrument:
    return ConnectedInstrument(
        address=address,
        manufacturer="Keithley",
        model="2602B",
        idn=resource.name,
        schema_key="keithley/smu/2600",
    )


def test_connect_and_list_session() -> None:
    rm = FakeResourceManager()
    manager = VisaSessionManager(lambda: rm)

    session = manager.connect("USB0::1", identify)

    assert session.instrument.address == "USB0::1"
    assert session.instrument.healthy is True
    assert len(rm.resources) == 1
    assert manager.list_connected() == [session.instrument]


def test_duplicate_connect_is_idempotent() -> None:
    rm = FakeResourceManager()
    manager = VisaSessionManager(lambda: rm)

    first = manager.connect("USB0::1", identify)
    second = manager.connect("USB0::1", identify)

    assert second is first
    assert len(rm.resources) == 1


def test_failed_identify_closes_temporary_resource() -> None:
    rm = FakeResourceManager()
    manager = VisaSessionManager(lambda: rm)

    def fail_identify(address: str, resource: FakeResource) -> ConnectedInstrument:
        raise RuntimeError("IDN failed")

    with pytest.raises(SessionConnectError, match="IDN failed"):
        manager.connect("USB0::1", fail_identify)

    assert rm.resources[0].closed == 1
    assert manager.list_connected() == []


def test_concurrent_duplicate_connect_closes_loser() -> None:
    rm = FakeResourceManager()
    manager = VisaSessionManager(lambda: rm)
    barrier = threading.Barrier(2)
    sessions = []

    def slow_identify(address: str, resource: FakeResource) -> ConnectedInstrument:
        barrier.wait()
        return identify(address, resource)

    threads = [
        threading.Thread(
            target=lambda: sessions.append(manager.connect("USB0::1", slow_identify))
        )
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sessions[0] is sessions[1]
    assert len(rm.resources) == 2
    assert sum(resource.closed for resource in rm.resources) == 1


def test_lease_serializes_concurrent_access() -> None:
    rm = FakeResourceManager()
    manager = VisaSessionManager(lambda: rm)
    manager.connect("USB0::1", identify)
    active = 0
    peak = 0
    state_lock = threading.Lock()

    def use_resource() -> None:
        nonlocal active, peak
        with manager.lease("USB0::1"):
            with state_lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with state_lock:
                active -= 1

    threads = [threading.Thread(target=use_resource) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert peak == 1


def test_lease_marks_session_unhealthy_after_io_error() -> None:
    rm = FakeResourceManager()
    manager = VisaSessionManager(lambda: rm)
    manager.connect("USB0::1", identify)
    rm.resources[0].fail_write = True

    with pytest.raises(RuntimeError, match="write failed"):
        with manager.lease("USB0::1") as resource:
            resource.write("FAIL")

    session = manager.get("USB0::1")
    assert session.healthy is False
    assert session.instrument.healthy is False
    assert "write failed" in (session.last_error or "")
    with pytest.raises(SessionUnhealthy):
        with manager.lease("USB0::1"):
            pass


def test_disconnect_closes_and_removes_session() -> None:
    rm = FakeResourceManager()
    manager = VisaSessionManager(lambda: rm)
    manager.connect("USB0::1", identify)

    instrument = manager.disconnect("USB0::1")

    assert instrument.address == "USB0::1"
    assert rm.resources[0].closed == 1
    with pytest.raises(SessionNotFound):
        manager.get("USB0::1")


def test_reconnect_replaces_resource() -> None:
    rm = FakeResourceManager()
    manager = VisaSessionManager(lambda: rm)
    manager.connect("USB0::1", identify)

    session = manager.reconnect("USB0::1", identify)

    assert len(rm.resources) == 2
    assert rm.resources[0].closed == 1
    assert session.resource is rm.resources[1]


def test_shutdown_closes_every_session_and_resource_manager() -> None:
    rm = FakeResourceManager()
    manager = VisaSessionManager(lambda: rm)
    manager.connect("USB0::1", identify)
    manager.connect("USB0::2", identify)

    errors = manager.shutdown()

    assert errors == []
    assert [resource.closed for resource in rm.resources] == [1, 1]
    assert rm.closed == 1
    assert manager.list_connected() == []
