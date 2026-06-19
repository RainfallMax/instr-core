"""Tests for exclusive instrument-address ownership."""

from __future__ import annotations

import threading

from instr_core.api.services.ownership_service import AddressOwnershipRegistry


def test_acquire_and_release_address() -> None:
    registry = AddressOwnershipRegistry()

    assert registry.acquire("USB0::1", "run-1") is True
    assert registry.snapshot() == {"USB0::1": "run-1"}
    assert registry.release("USB0::1", "run-1") is True
    assert registry.snapshot() == {}


def test_second_owner_is_rejected() -> None:
    registry = AddressOwnershipRegistry()

    assert registry.acquire("USB0::1", "run-1") is True
    assert registry.acquire("USB0::1", "run-2") is False
    assert registry.snapshot() == {"USB0::1": "run-1"}


def test_same_owner_can_release_only_its_address() -> None:
    registry = AddressOwnershipRegistry()
    registry.acquire("USB0::1", "run-1")

    assert registry.release("USB0::1", "run-2") is False
    assert registry.snapshot() == {"USB0::1": "run-1"}


def test_acquire_many_is_atomic() -> None:
    registry = AddressOwnershipRegistry()
    registry.acquire("USB0::2", "existing")

    assert registry.acquire_many(["USB0::1", "USB0::2"], "run-1") is False
    assert registry.snapshot() == {"USB0::2": "existing"}


def test_concurrent_acquire_has_one_winner() -> None:
    registry = AddressOwnershipRegistry()
    barrier = threading.Barrier(10)
    winners: list[str] = []
    result_lock = threading.Lock()

    def compete(owner: str) -> None:
        barrier.wait()
        if registry.acquire("USB0::1", owner):
            with result_lock:
                winners.append(owner)

    threads = [
        threading.Thread(target=compete, args=(f"run-{index}",))
        for index in range(10)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(winners) == 1
    assert registry.snapshot() == {"USB0::1": winners[0]}
