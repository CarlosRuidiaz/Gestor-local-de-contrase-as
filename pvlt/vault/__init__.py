"""Session, entries, vault operations and generator. Only layer that holds the KEK."""

from pvlt.vault.errors import (
    EntryNotFoundError,
    SessionLockedError,
    TamperedContentError,
    ValidationError,
    VaultError,
    VaultExistsError,
    WrongPasswordError,
)
from pvlt.vault.generator import entropy_bits, generate
from pvlt.vault.model import Entry, EntrySummary, GeneratorSettings, Settings
from pvlt.vault.vault import (
    ConflictReason,
    ImportDecision,
    ImportItem,
    ImportPreview,
    ImportResult,
    Vault,
)
from pvlt.vault.workspace import Workspace

__all__ = [
    "ConflictReason",
    "Entry",
    "EntryNotFoundError",
    "EntrySummary",
    "GeneratorSettings",
    "ImportDecision",
    "ImportItem",
    "ImportPreview",
    "ImportResult",
    "SessionLockedError",
    "Settings",
    "TamperedContentError",
    "ValidationError",
    "Vault",
    "VaultError",
    "VaultExistsError",
    "Workspace",
    "WrongPasswordError",
    "entropy_bits",
    "generate",
]
