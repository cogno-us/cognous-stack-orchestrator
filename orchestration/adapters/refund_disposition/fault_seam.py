"""Bounded DEVELOPMENT-ONLY fault seam for check C (post-commit lost acknowledgment). Not a production feature.

It subclasses the pinned `EffectiveGrantDestination` inside the adapter; no component source is changed and Runtime semantics are not
altered. After the durable commit the native `simulate="lost_ack"` path raises `TimeoutError`; this subclass then makes the destination's
read path unavailable, so the Runtime's own follow-up observation (and the Control Plane's) fails and the native outcome is genuinely
`unknown` while exactly one effect row is committed. `heal()` ends the simulated outage. A fresh, unfaulted destination object is
used for any later reconciliation.
"""
from __future__ import annotations

from typing import Any


def make_fault_destination_class(base: type) -> type:
    class LostAckThenUnreadable(base):  # type: ignore[misc, valid-type]
        dev_fault = "lost_ack_observation_unavailable"
        _unreadable = False

        def commit(self, snapshot: Any, **kwargs: Any) -> dict:
            try:
                return super().commit(snapshot, **kwargs)
            except TimeoutError:
                self._unreadable = True  # the row IS committed; only the acknowledgment and the read path are lost
                raise

        def observe_bound(self, snapshot: Any) -> dict:
            if self._unreadable:
                raise OSError("synthetic destination observation unavailable (development fault seam)")
            return super().observe_bound(snapshot)

        def heal(self) -> None:
            self._unreadable = False

    return LostAckThenUnreadable
