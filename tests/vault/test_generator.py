"""T11: generator length, class coverage and absence of bias (chi-square)."""

from __future__ import annotations

import itertools
import math
import secrets
from collections import Counter

import pytest

from pvlt.vault import GeneratorSettings, ValidationError, entropy_bits, generate, generator

CLASS_NAMES = ("lower", "upper", "digits", "symbols")
CLASS_CHARS = {
    "lower": generator.LOWER,
    "upper": generator.UPPER,
    "digits": generator.DIGITS,
    "symbols": generator.SYMBOLS,
}
ALL_COMBINATIONS = [combo for r in range(1, 5) for combo in itertools.combinations(CLASS_NAMES, r)]


def settings(combo: tuple[str, ...], length: int = 20) -> GeneratorSettings:
    return GeneratorSettings(length=length, **{name: name in combo for name in CLASS_NAMES})


def chi2_critical(df: int, z: float = 4.265) -> float:
    """Upper critical value of chi-square (Wilson-Hilferty). z = 4.265 is p = 1e-5.

    A correct generator fails a check about once in 100 000 runs. A generator
    with a real bias produces statistics several times above this value.
    """
    return float(df * (1 - 2 / (9 * df) + z * math.sqrt(2 / (9 * df))) ** 3)


def chi2_uniform(counts: Counter[str], alphabet: str) -> float:
    total = sum(counts[ch] for ch in alphabet)
    expected = total / len(alphabet)
    return sum((counts[ch] - expected) ** 2 / expected for ch in alphabet)


# --- Alphabet ---------------------------------------------------------------


def test_alphabets_match_the_design() -> None:
    assert generator.LOWER == "abcdefghijklmnopqrstuvwxyz"
    assert generator.UPPER == "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    assert generator.DIGITS == "0123456789"
    assert generator.SYMBOLS == "!#$%&()*+,-./:;<=>?@[]^_{|}~"
    for forbidden in "\"'`\\ ":
        assert forbidden not in generator.SYMBOLS
    union = generator.LOWER + generator.UPPER + generator.DIGITS + generator.SYMBOLS
    assert len(set(union)) == len(union) == 90  # classes do not overlap


def test_generator_uses_only_the_secrets_module(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    real_choice = secrets.choice

    def counting_choice(seq: str) -> str:
        nonlocal calls
        calls += 1
        return real_choice(seq)

    monkeypatch.setattr(generator.secrets, "choice", counting_choice)
    generate(settings(("lower",), length=50))
    assert calls == 50  # one draw per character and no other source of randomness


# --- T11: 10 000 passwords over every combination of classes ----------------


@pytest.mark.parametrize("combo", ALL_COMBINATIONS, ids="+".join)
def test_t11_length_and_classes(combo: tuple[str, ...]) -> None:
    """15 combinations x 700 = 10 500 passwords, with varying lengths."""
    alphabet = set("".join(CLASS_CHARS[name] for name in combo))
    seen: set[str] = set()
    for i in range(700):
        length = (8, 12, 20, 64, 128)[i % 5]
        password = generate(settings(combo, length))
        assert len(password) == length
        assert set(password) <= alphabet
        for name in combo:
            assert any(ch in CLASS_CHARS[name] for ch in password), name
        seen.add(password)
    assert len(seen) == 700


@pytest.mark.parametrize("combo", ALL_COMBINATIONS, ids="+".join)
def test_t11_no_bias_inside_each_class(combo: tuple[str, ...]) -> None:
    """Within a class every character is exactly equally likely, for any length.

    This is the right uniformity statement for rejection sampling: requiring every
    class to appear shifts a little weight between classes on short passwords
    (the small ones, like digits, become slightly more frequent), but it can never
    favour one character over another of the same class.
    """
    counts: Counter[str] = Counter()
    for _ in range(1000):
        counts.update(generate(settings(combo, 20)))
    for name in combo:
        chars = CLASS_CHARS[name]
        assert chi2_uniform(counts, chars) < chi2_critical(len(chars) - 1), name


def test_t11_no_bias_over_the_whole_alphabet() -> None:
    """At length 128 a class is missing with probability below 1e-6, so rejection is
    negligible and all 90 characters must be uniform. 10 000 passwords, 1.28 M characters.
    """
    combo = CLASS_NAMES
    alphabet = "".join(CLASS_CHARS[name] for name in combo)
    counts: Counter[str] = Counter()
    for _ in range(10_000):
        counts.update(generate(settings(combo, 128)))
    assert sum(counts.values()) == 1_280_000
    assert chi2_uniform(counts, alphabet) < chi2_critical(len(alphabet) - 1)


def test_t11_no_positional_bias() -> None:
    """The first and the last position are as uniform as the rest."""
    first: Counter[str] = Counter()
    last: Counter[str] = Counter()
    for _ in range(20_000):
        password = generate(settings(("digits",), 8))
        first[password[0]] += 1
        last[password[-1]] += 1
    assert chi2_uniform(first, generator.DIGITS) < chi2_critical(9)
    assert chi2_uniform(last, generator.DIGITS) < chi2_critical(9)


def test_chi2_helper_detects_a_biased_generator() -> None:
    """Sanity check of the test itself: modulo bias of a byte over 90 symbols is caught."""
    alphabet = "".join(CLASS_CHARS[name] for name in CLASS_NAMES)
    counts = Counter(alphabet[b % 90] for b in secrets.token_bytes(300_000))
    assert chi2_uniform(counts, alphabet) > chi2_critical(89)


# --- Entropy and validation -------------------------------------------------


@pytest.mark.parametrize(
    ("combo", "length", "expected"),
    [
        (CLASS_NAMES, 20, 20 * math.log2(90)),
        (("digits",), 8, 8 * math.log2(10)),
        (("lower", "upper"), 32, 32 * math.log2(52)),
        (("symbols",), 128, 128 * math.log2(28)),
    ],
)
def test_entropy(combo: tuple[str, ...], length: int, expected: float) -> None:
    assert entropy_bits(settings(combo, length)) == pytest.approx(expected)


def test_default_settings_give_about_130_bits() -> None:
    assert entropy_bits(GeneratorSettings()) == pytest.approx(129.84, abs=0.01)
    assert len(generate(GeneratorSettings())) == 20


@pytest.mark.parametrize("length", [0, 7, 129, 1000, -1])
def test_length_out_of_range(length: int) -> None:
    with pytest.raises(ValidationError):
        GeneratorSettings(length=length)


def test_at_least_one_class_is_required() -> None:
    with pytest.raises(ValidationError) as info:
        GeneratorSettings(lower=False, upper=False, digits=False, symbols=False)
    assert info.value.field == "generator.classes"
