"""Curated reference facts that are missing from (or spread across) the docs.

These are stable, factual data sets used by several layers:

* pre-defined energy group structures for the ``ene`` card (type 4);
* short overlay notes for cards where the online manual is incomplete
  (e.g. ``ene`` type 4, ``dr`` special responses, decay source).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_STRUCTURES_PATH = Path(__file__).with_name("energy_structures.json")
_DATA: dict[str, Any] | None = None


def data() -> dict[str, Any]:
    global _DATA
    if _DATA is None:
        try:
            _DATA = json.loads(_STRUCTURES_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _DATA = {"structures": []}
    return _DATA


def structures() -> list[dict[str, Any]]:
    return list(data().get("structures", []))


def structure_names(include_extended: bool = True) -> set[str]:
    names: set[str] = set()
    for entry in structures():
        names.add(entry["name"])
        if include_extended and entry.get("extended"):
            names.add(entry["extended"])
    return names


def structures_text(limit: int = 60) -> str:
    rows = ["Name | Groups | Description"]
    for entry in structures()[:limit]:
        rows.append(f"{entry['name']} | {entry['groups']} | {entry['description']}")
    return "\n".join(rows)


LEGACY_NOTES: dict[str, str] = {
    "ene": (
        "Pre-defined group structures (older manual, still used by 2.1.x/2.2.x): "
        "TYPE = 4 selects a built-in structure by name, e.g. 'ene e 4 scale44'. "
        "Names have optional '_ext' versions spanning all energies (0...inf). "
        "Pre-defined structures cannot be used directly in detectors; redefine them "
        "with an ene card first. Use get_reference('energy-structures') or "
        "list_energy_structures for the full list."
    ),
    "dec": (
        "Negative response numbers select special macroscopic responses, e.g. "
        "-1 flux, -2 total cross section, -4 capture, -6 total absorption, "
        "-9 total energy production, -100 user-defined response defined by a fun card "
        "(dr -100 NAME). See the ENDF reaction appendix for the complete list."
    ),
    "dr": (
        "Negative response numbers select special macroscopic responses (see the ENDF "
        "reaction appendix); -100 uses a user-defined function declared with a fun card: "
        "'fun NAME 1 5 ...' + 'dr -100 NAME'. Without the matching fun card the detector "
        "will fail."
    ),
    "sg": (
        "Radioactive decay source: 'sg DMAT MODE', where DMAT is a material name or -1 "
        "for all radioactive materials; MODE 1 analog, 2 implicit. The emitting nuclides "
        "must carry decay data (ZAI without library suffix such as 270600 or Cm-250). "
        "With set declib (and set nfylib for spontaneous-fission neutrons) Serpent writes "
        "the source spectra to [input]_gsrc.m / [input]_nsrc.m; their 'tot' value is used "
        "for set srcrate."
    ),
}


def legacy_note(card_name: str) -> str | None:
    return LEGACY_NOTES.get(card_name.lower())
