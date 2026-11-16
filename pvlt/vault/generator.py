"""Password generator (docs/diseno.md, section 4.8). Randomness comes only from `secrets`."""

from __future__ import annotations

import math
import secrets
import string
from typing import Final

from pvlt.vault.errors import ValidationError
from pvlt.vault.model import GENERATOR_LENGTH_MAX, GENERATOR_LENGTH_MIN, GeneratorSettings

LOWER: Final = string.ascii_lowercase
UPPER: Final = string.ascii_uppercase
DIGITS: Final = string.digits
# No quotes and no backslash, to avoid trouble when pasting.
SYMBOLS: Final = "!#$%&()*+,-./:;<=>?@[]^_{|}~"


def selected_classes(settings: GeneratorSettings) -> tuple[str, ...]:
    classes = tuple(
        chars
        for enabled, chars in (
            (settings.lower, LOWER),
            (settings.upper, UPPER),
            (settings.digits, DIGITS),
            (settings.symbols, SYMBOLS),
        )
        if enabled
    )
    if not classes:
        raise ValidationError("generator.classes")
    if not GENERATOR_LENGTH_MIN <= settings.length <= GENERATOR_LENGTH_MAX:
        raise ValidationError("generator.length")
    return classes


def generate(settings: GeneratorSettings) -> str:
    """Rejection sampling: uniform candidates over the whole alphabet, kept only if
    every selected class appears. The result is uniform over the valid passwords.
    """
    classes = selected_classes(settings)
    alphabet = "".join(classes)
    while True:
        candidate = "".join(secrets.choice(alphabet) for _ in range(settings.length))
        if all(any(ch in cls for ch in candidate) for cls in classes):
            return candidate


def entropy_bits(settings: GeneratorSettings) -> float:
    """length x log2(alphabet size), the figure shown to the user.

    It is an upper bound: discarding candidates that miss a class removes a
    fraction of a bit (about 0.15 bits with the default settings).
    """
    alphabet_size = sum(len(cls) for cls in selected_classes(settings))
    return settings.length * math.log2(alphabet_size)
