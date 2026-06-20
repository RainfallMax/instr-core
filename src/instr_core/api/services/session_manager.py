"""Thread-safe lifecycle management for reusable VISA sessions."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterator

from ..models import ConnectedInstrument

IdentifyCallback = Callable[[str, Any], ConnectedInstrument]


class SessionNotFound(LookupError):
    """No managed session exists for an address."""


class SessionUnhealthy(RuntimeError):
    """A managed session is unhealthy and requires reconnect."""


class SessionConnectError(RuntimeError):
    """Opening or identifying a VISA resource failed."""


class SessionCloseError(RuntimeError):
    """Closing a VISA resource failed."""


@dataclass
class ManagedVisaSession:
    """One reusable VISA resource and its observable connection metadata."""

    address: str
    resource: Any
    instrument: ConnectedInstrument
    connected_at: str
    healthy: bool = True
    last_error: str | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)

    def mark_unhealthy(self, exc: Exception) -> None:
        """Record an I/O failure on the session and response metadata."""
        self.healthy = False
        self.last_error = str(exc)
        self.instrument.healthy = False
        self.instrument.last_error = str(exc)


class ManagedResourceProxy:
    """Proxy that marks only the resource whose I/O method raises."""

    def __init__(self, session: ManagedVisaSession) -> None:
        object.__setattr__(self, "_session", session)

    def __getattr__(self, name: str) -> Any:
        session: ManagedVisaSession = object.__getattribute__(self, "_session")
        attribute = getattr(session.resource, name)
        if not callable(attribute):
            return attribute

        def call(*args: Any, **kwargs: Any) -> Any:
            try:
                return attribute(*args, **kwargs)
            except Exception as exc:
                session.mark_unhealthy(exc)
                raise

        return call

    def __setattr__(self, name: str, value: Any) -> None:
        session: ManagedVisaSession = object.__getattribute__(self, "_session")
        try:
            setattr(session.resource, name, value)
        except Exception as exc:
            session.mark_unhealthy(exc)
            raise


class VisaSessionManager:
    """Own and serialize all connected VISA resources."""

    def __init__(self, resource_manager_factory: Callable[[], Any]) -> None:
        self._resource_manager_factory = resource_manager_factory
        self._resource_manager: Any | None = None
        self._sessions: dict[str, ManagedVisaSession] = {}
        self._lock = threading.RLock()

    def _resource_manager_instance(self) -> Any:
        with self._lock:
            if self._resource_manager is None:
                self._resource_manager = self._resource_manager_factory()
            return self._resource_manager

    def connect(
        self,
        address: str,
        identify: IdentifyCallback,
    ) -> ManagedVisaSession:
        """Open and atomically publish one fully identified session."""
        address = address.strip()
        if not address:
            raise SessionConnectError("VISA address cannot be empty")

        with self._lock:
            existing = self._sessions.get(address)
            if existing is not None and existing.healthy:
                return existing

        resource: Any | None = None
        try:
            resource = self._resource_manager_instance().open_resource(address)
            instrument = identify(address, resource)
            connected_at = datetime.now(timezone.utc).isoformat()
            instrument.connected_at = connected_at
            instrument.healthy = True
            instrument.last_error = None
            candidate = ManagedVisaSession(
                address=address,
                resource=resource,
                instrument=instrument,
                connected_at=connected_at,
            )
        except Exception as exc:
            if resource is not None:
                try:
                    resource.close()
                except Exception:
                    pass
            raise SessionConnectError(
                f"Failed to connect to '{address}': {exc}"
            ) from exc

        with self._lock:
            existing = self._sessions.get(address)
            if existing is not None and existing.healthy:
                resource.close()
                return existing
            self._sessions[address] = candidate
            return candidate

    def get(self, address: str) -> ManagedVisaSession:
        """Return a managed session or raise when disconnected."""
        with self._lock:
            session = self._sessions.get(address)
        if session is None:
            raise SessionNotFound(f"Address '{address}' is not connected")
        return session

    def mark_unhealthy(self, address: str, error: str) -> None:
        """Mark a connected session unhealthy after background I/O failure."""
        session = self.get(address)
        with session.lock:
            session.mark_unhealthy(RuntimeError(error))

    @contextmanager
    def lease(self, address: str) -> Iterator[Any]:
        """Yield a healthy resource while holding its per-address lock."""
        session = self.get(address)
        with session.lock:
            if not session.healthy:
                raise SessionUnhealthy(
                    f"Address '{address}' is unhealthy: {session.last_error}"
                )
            yield ManagedResourceProxy(session)

    def list_connected(self) -> list[ConnectedInstrument]:
        """Return connection metadata ordered deterministically."""
        with self._lock:
            sessions = list(self._sessions.values())
        sessions.sort(key=lambda item: (item.connected_at, item.address))
        return [session.instrument.model_copy(deep=True) for session in sessions]

    def disconnect(self, address: str) -> ConnectedInstrument:
        """Remove and close a managed session."""
        with self._lock:
            session = self._sessions.pop(address, None)
        if session is None:
            raise SessionNotFound(f"Address '{address}' is not connected")
        try:
            with session.lock:
                session.resource.close()
        except Exception as exc:
            raise SessionCloseError(
                f"Failed to close VISA resource '{address}': {exc}"
            ) from exc
        return session.instrument.model_copy(deep=True)

    def reconnect(
        self,
        address: str,
        identify: IdentifyCallback,
    ) -> ManagedVisaSession:
        """Replace an existing session with a freshly identified resource."""
        try:
            self.disconnect(address)
        except SessionNotFound:
            pass
        return self.connect(address, identify)

    def shutdown(self) -> list[str]:
        """Close every session and the ResourceManager, collecting errors."""
        with self._lock:
            addresses = list(self._sessions)
        errors: list[str] = []
        for address in addresses:
            try:
                self.disconnect(address)
            except Exception as exc:
                errors.append(str(exc))

        with self._lock:
            resource_manager = self._resource_manager
            self._resource_manager = None
        if resource_manager is not None and hasattr(resource_manager, "close"):
            try:
                resource_manager.close()
            except Exception as exc:
                errors.append(f"Failed to close VISA ResourceManager: {exc}")
        return errors
