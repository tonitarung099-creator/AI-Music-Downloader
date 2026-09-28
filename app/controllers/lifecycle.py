from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class OperationCoordinator:
    """Own minimal operation identity and stale-event rejection rules."""

    import_id: str | None = None
    queue_batch_id: str | None = None
    agent_id: str | None = None
    closing: bool = False

    def begin_import(self, import_id: str) -> None:
        if self.closing:
            raise RuntimeError("Aplikasi sedang ditutup.")
        self.import_id = import_id

    def is_current_import(self, import_id: str) -> bool:
        return not self.closing and self.import_id == import_id

    def finish_import(self, import_id: str) -> bool:
        if self.import_id != import_id:
            return False
        self.import_id = None
        return True

    def invalidate_import(self) -> None:
        self.import_id = None

    def begin_queue(self, batch_id: str) -> None:
        if self.closing:
            raise RuntimeError("Aplikasi sedang ditutup.")
        self.queue_batch_id = batch_id

    def finish_queue(self, batch_id: str | None = None) -> bool:
        if batch_id is not None and self.queue_batch_id != batch_id:
            return False
        if self.queue_batch_id is None:
            return False
        self.queue_batch_id = None
        return True

    def begin_agent(self, agent_id: str) -> None:
        if self.closing:
            raise RuntimeError("Aplikasi sedang ditutup.")
        self.agent_id = agent_id

    def is_current_agent(self, agent_id: str) -> bool:
        return not self.closing and self.agent_id == agent_id

    def finish_agent(self, agent_id: str) -> bool:
        if self.agent_id != agent_id:
            return False
        self.agent_id = None
        return True

    def request_shutdown(self) -> None:
        self.closing = True
        self.import_id = None
        self.agent_id = None
