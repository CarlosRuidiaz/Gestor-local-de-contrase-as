"""Vault failures, one class per category. Messages are fixed and never carry user data."""

from __future__ import annotations


class VaultError(Exception):
    """Base class of every failure raised by the vault layer."""


class WrongPasswordError(VaultError):
    """Check 3 failed: the wrapped key did not open with the derived KEK.

    Altering the salt, the header or W produces this same error, because without
    the key it cannot be told apart from a wrong password (declared limitation).
    """

    def __init__(self) -> None:
        super().__init__("Contraseña incorrecta")


class TamperedContentError(VaultError):
    """Check 4 failed: the content did not authenticate, or is not a valid vault content.

    `reason` is a fixed identifier of the rule that failed, never a value from the file.
    """

    def __init__(self, reason: str = "tag") -> None:
        super().__init__("Contenido manipulado")
        self.reason = reason


class SessionLockedError(VaultError):
    """The vault is locked (button, shutdown or inactivity). Unlock it again."""

    def __init__(self) -> None:
        super().__init__("La bóveda está bloqueada")


class ValidationError(VaultError):
    """User input rejected. `field` names the offending field, never its value."""

    def __init__(self, field: str) -> None:
        super().__init__("Dato inválido")
        self.field = field


class EntryNotFoundError(VaultError):
    def __init__(self) -> None:
        super().__init__("La entrada no existe")


class VaultExistsError(VaultError):
    """Creating or exporting would overwrite an existing file."""

    def __init__(self) -> None:
        super().__init__("Ya existe un archivo en esa ruta")
