"""Variable registry for the standalone scenario path classifier."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


VALID_TRANSFORMS = {"level", "yoy_pct", "qoq_ann_pct", "diff"}
VALID_ROLES = {"spine", "signature"}
VALID_COMBINES = {"subtract"}


class RegistryError(ValueError):
    """Raised when the state-vector registry is malformed."""


@dataclass(frozen=True)
class VariableSpec:
    name: str
    transform: str
    roles: tuple[str, ...]
    fred_series: str | None = None
    fred_components: tuple[str, ...] | None = None
    combine: str | None = None
    signature_map: str | None = None
    bounds: tuple[float, float] | None = None

    @property
    def is_signature(self) -> bool:
        return "signature" in self.roles

    @property
    def is_spine(self) -> bool:
        return "spine" in self.roles

    @property
    def fred_ids(self) -> tuple[str, ...]:
        if self.fred_series:
            return (self.fred_series,)
        return self.fred_components or ()


class VariableRegistry:
    def __init__(self, variables: list[VariableSpec], source_path: Path) -> None:
        if not variables:
            raise RegistryError("state vector registry contains no variables")
        self.variables = variables
        self.source_path = source_path
        self._by_name = {variable.name: variable for variable in variables}
        if len(self._by_name) != len(variables):
            raise RegistryError("state vector registry contains duplicate variable names")

    @classmethod
    def load(cls, path: str | Path | None = None) -> "VariableRegistry":
        source_path = Path(path) if path is not None else default_state_vector_path()
        if not source_path.is_file():
            raise RegistryError(f"state vector config not found: {source_path}")
        with source_path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        if not isinstance(raw, dict):
            raise RegistryError(f"state vector config must be a YAML mapping: {source_path}")
        variables_raw = raw.get("variables")
        if not isinstance(variables_raw, dict) or not variables_raw:
            raise RegistryError(
                f"state vector config must contain a non-empty variables mapping: {source_path}"
            )

        variables = [
            _parse_variable(name, payload, source_path)
            for name, payload in variables_raw.items()
        ]
        return cls(variables, source_path)

    def get(self, name: str) -> VariableSpec:
        try:
            return self._by_name[name]
        except KeyError as exc:
            raise RegistryError(f"unknown state-vector variable: {name}") from exc

    def signature_variables(self) -> list[VariableSpec]:
        return [variable for variable in self.variables if variable.is_signature]

    def spine_variables(self) -> list[VariableSpec]:
        return [variable for variable in self.variables if variable.is_spine]

    def variable_names(self) -> list[str]:
        return [variable.name for variable in self.variables]

    def signature_variable_names(self) -> list[str]:
        return [variable.name for variable in self.signature_variables()]

    def spine_variable_names(self) -> list[str]:
        return [variable.name for variable in self.spine_variables()]

    def unique_fred_series_ids(self) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for variable in self.variables:
            for series_id in variable.fred_ids:
                if series_id not in seen:
                    seen.add(series_id)
                    ordered.append(series_id)
        return ordered


def default_state_vector_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "state_vector.yaml"


def _parse_variable(
    name: str,
    payload: Any,
    source_path: Path,
) -> VariableSpec:
    if not isinstance(name, str) or not name.strip():
        raise RegistryError(f"state vector variable has empty name in {source_path}")
    clean_name = name.strip()
    if not isinstance(payload, dict):
        raise RegistryError(
            f"variable '{clean_name}' must be a YAML mapping in {source_path}"
        )

    transform = payload.get("transform")
    if transform not in VALID_TRANSFORMS:
        raise RegistryError(
            f"variable '{clean_name}' has unknown transform '{transform}'. "
            f"Valid transforms: {sorted(VALID_TRANSFORMS)}"
        )

    roles_raw = payload.get("roles")
    if not isinstance(roles_raw, list) or not roles_raw:
        raise RegistryError(f"variable '{clean_name}' must define a non-empty roles list")
    roles = tuple(str(role).strip() for role in roles_raw if str(role).strip())
    if not roles:
        raise RegistryError(f"variable '{clean_name}' roles list is empty after cleanup")
    unknown_roles = sorted(set(roles) - VALID_ROLES)
    if unknown_roles:
        raise RegistryError(
            f"variable '{clean_name}' has unknown roles {unknown_roles}. "
            f"Valid roles: {sorted(VALID_ROLES)}"
        )

    fred_series = _optional_string(payload.get("fred_series"))
    fred_components = _optional_string_list(payload.get("fred_components"))
    if bool(fred_series) == bool(fred_components):
        raise RegistryError(
            f"variable '{clean_name}' must define exactly one of fred_series or fred_components"
        )

    combine = _optional_string(payload.get("combine"))
    if fred_components:
        if combine not in VALID_COMBINES:
            raise RegistryError(
                f"variable '{clean_name}' has unsupported combine '{combine}'. "
                "Only subtract is supported."
            )
        if len(fred_components) < 2:
            raise RegistryError(
                f"variable '{clean_name}' fred_components must include at least two series"
            )
    elif combine is not None:
        raise RegistryError(
            f"variable '{clean_name}' defines combine but does not use fred_components"
        )

    signature_map = _optional_string(payload.get("signature_map"))
    if "signature" in roles and not signature_map:
        raise RegistryError(
            f"variable '{clean_name}' has signature role but no signature_map"
        )
    if "signature" not in roles and signature_map:
        raise RegistryError(
            f"variable '{clean_name}' defines signature_map without signature role"
        )
    bounds = _optional_bounds(payload.get("bounds"), clean_name)

    allowed_keys = {
        "fred_series",
        "fred_components",
        "combine",
        "transform",
        "roles",
        "signature_map",
        "bounds",
    }
    unknown_keys = sorted(set(payload) - allowed_keys)
    if unknown_keys:
        raise RegistryError(
            f"variable '{clean_name}' has unknown keys {unknown_keys} in {source_path}"
        )

    return VariableSpec(
        name=clean_name,
        transform=str(transform),
        roles=roles,
        fred_series=fred_series,
        fred_components=tuple(fred_components) if fred_components else None,
        combine=combine,
        signature_map=signature_map,
        bounds=bounds,
    )


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise RegistryError(f"expected non-empty string, got {value!r}")
    return value.strip()


def _optional_string_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise RegistryError(f"expected non-empty string list, got {value!r}")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise RegistryError(f"expected non-empty string in list, got {item!r}")
        out.append(item.strip())
    return out


def _optional_bounds(value: Any, variable_name: str) -> tuple[float, float] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 2:
        raise RegistryError(
            f"variable '{variable_name}' bounds must be a two-item list [lo, hi]"
        )
    try:
        lo = float(value[0])
        hi = float(value[1])
    except (TypeError, ValueError) as exc:
        raise RegistryError(
            f"variable '{variable_name}' bounds must contain numeric values"
        ) from exc
    if lo >= hi:
        raise RegistryError(
            f"variable '{variable_name}' bounds must satisfy lo < hi; got {value!r}"
        )
    return lo, hi
