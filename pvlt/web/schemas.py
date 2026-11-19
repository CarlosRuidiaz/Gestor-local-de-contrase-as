"""Request bodies. Strict types, no unknown keys, and no user data in any `repr`.

Lengths and contents are validated by the vault layer, which owns the rules.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

# Every value typed by the user is hidden from the model's repr.
Secret = Annotated[str, Field(repr=False)]
OptionalSecret = Annotated[str | None, Field(repr=False)]


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class TokenBody(Body):
    token: Secret


class ConfirmBody(Body):
    confirm: bool


class CreateBody(Body):
    password: Secret
    confirm: Secret
    config: Literal["A", "B", "C"] = "B"


class UnlockBody(Body):
    password: Secret


class EntryBody(Body):
    site: Secret
    username: Secret = ""
    password: Secret
    notes: Secret = ""


class EntryUpdateBody(Body):
    site: OptionalSecret = None
    username: OptionalSecret = None
    password: OptionalSecret = None
    notes: OptionalSecret = None


class GeneratorBody(Body):
    length: int = 20
    lower: bool = True
    upper: bool = True
    digits: bool = True
    symbols: bool = True


class SettingsBody(Body):
    autolock_seconds: int | None = None
    generator: GeneratorBody | None = None


class ChangePasswordBody(Body):
    current: Secret
    new: Secret
    confirm: Secret


class ExportBody(Body):
    filename: str
    password: Secret
    confirm: Secret
    overwrite: bool = False


class ImportPreviewBody(Body):
    filename: str
    password: Secret


class ImportApplyBody(Body):
    preview_id: str
    decisions: dict[str, Literal["skip", "replace", "keep_both"]] = {}
