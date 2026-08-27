#!/usr/bin/env python3
"""Validação estrita dos números ASCII produzidos pelo simulador VJ5G."""

from __future__ import annotations

import csv
import math
import re
from pathlib import Path


ASCII_NUMBER = re.compile(
    r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$"
)


def validate_numeric_csv(
    path: Path,
    numeric_columns: set[str],
    bounds: dict[str, tuple[float | None, float | None]] | None = None,
) -> None:
    """Rejeita CSV vazio, colunas ausentes e números alterados por locale.

    O formato canônico usa vírgula entre campos e ponto decimal. Uma vírgula
    decimal cria colunas excedentes no ``DictReader`` e também é rejeitada.
    """
    bounds = bounds or {}
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"{path.name} ausente ou vazio")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = numeric_columns - set(reader.fieldnames or ())
        if missing:
            raise RuntimeError(f"{path.name} sem colunas numéricas: {sorted(missing)}")
        count = 0
        for line_number, row in enumerate(reader, start=2):
            count += 1
            if None in row:
                raise RuntimeError(
                    f"{path.name}:{line_number}: campos excedentes; possível vírgula decimal"
                )
            for column in numeric_columns:
                raw = (row.get(column) or "").strip()
                if not ASCII_NUMBER.fullmatch(raw):
                    raise RuntimeError(
                        f"{path.name}:{line_number}:{column}: número não canônico {raw!r}"
                    )
                value = float(raw)
                if not math.isfinite(value):
                    raise RuntimeError(
                        f"{path.name}:{line_number}:{column}: valor não finito"
                    )
                lower, upper = bounds.get(column, (None, None))
                if lower is not None and value < lower:
                    raise RuntimeError(
                        f"{path.name}:{line_number}:{column}: {value} < {lower}"
                    )
                if upper is not None and value > upper:
                    raise RuntimeError(
                        f"{path.name}:{line_number}:{column}: {value} > {upper}"
                    )
    if count == 0:
        raise RuntimeError(f"{path.name} sem registros")

