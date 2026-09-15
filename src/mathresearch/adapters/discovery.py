"""Read-only discovery of supported host CLIs."""

from __future__ import annotations

from dataclasses import dataclass
import shutil


@dataclass(frozen=True)
class AdapterAvailability:
    """Whether a supported adapter executable can be resolved on PATH."""

    adapter_id: str
    executable: str | None
    capability_safe: bool = True
    reason: str | None = None

    @property
    def available(self) -> bool:
        return self.executable is not None and self.capability_safe

    def to_json(self) -> dict[str, bool | str]:
        """Return the stable public diagnostic representation."""
        return {"id": self.adapter_id, "available": self.available}


def discover_built_in_adapters() -> tuple[AdapterAvailability, ...]:
    """Resolve built-in adapter executables without invoking them."""
    claude = AdapterAvailability("claude", shutil.which("claude"))
    codex = AdapterAvailability(
        "codex",
        shutil.which("codex"),
        capability_safe=False,
        reason="Codex 0.154.0 cannot enforce disabled shell execution for the reasoning-only MVP profile",
    )
    return (claude, codex)
