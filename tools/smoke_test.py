#!/usr/bin/env python3
"""
smoke_test.py — HARNESS-SIDE per-file type-construction smoke gate.

This is a harness-owned validation tool run by runner.py (or manually by the
operator). It is NOT exposed to any agent's tool_allow_list — the coder never
sees or calls it.

For one staged `.py` file it:
  1. imports the module (with `src` importable so the edited file's
     cross-module type annotations resolve);
  2. for every pydantic ``BaseModel`` subclass *defined in that file*, probes
     its typed containers (``DictMap[X]`` / ``dict[..., X]`` with ``X`` a
     BaseModel): it builds a real ``X`` instance (via ``construct``, no
     validation) and assigns it into the container, then validates the parent
     model;
  3. if the container rejects the model instance (e.g. ``ExternalPillarTriggerMap
     (DictMap[str])`` given an ``ExternalPillarTrigger``), prints the error and
     exits 1 — this is BUG 2 in docs/01_fix.md (wrong container value type).

This is a *type-construction* check, not an execution test. It does NOT fail
on ordinary Literal/enum field mismatches (those are caught by ruff/pyright);
it targets only the class of bug where a typed container's value type cannot
actually hold the instances the code puts into it.

CLI:
    smoke_test.py <file>   -> prints a single JSON line and exits 0/1.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from pathlib import Path
from typing import Any

from pydantic import BaseModel

SCRIPT_DIR = Path(__file__).resolve().parent  # kit-tools/
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # target repo root

# Environmental import failures (DB/network at import time) must NOT block a
# coder — they are the architect's runtime concern, not a type bug (00_fix Fix H).
_ENV_ERRORS: tuple[type[BaseException], ...] = (ConnectionError, OSError)
try:
    import psycopg2

    _ENV_ERRORS = _ENV_ERRORS + (psycopg2.OperationalError,)
except (OSError, ValueError, TypeError, KeyError, AttributeError):
    pass
try:
    from sqlalchemy.exc import OperationalError as _SQLOperationalError

    _ENV_ERRORS = _ENV_ERRORS + (_SQLOperationalError,)
except (OSError, ValueError, TypeError, KeyError, AttributeError):
    pass


def _sample_base_model(ann: type) -> Any:
    """Build a real (validated) instance of a BaseModel for container probing."""
    data: dict[str, Any] = {}
    for name, field in ann.model_fields.items():
        data[name] = _permissive_value(field.annotation)
    try:
        return ann.model_validate(data)
    except (ValueError, TypeError):
        # Fall back to construct (un-validated) if validation fails on strict
        # Literal/enum fields — still a real instance for container-type checks.
        return ann.model_construct(**data)


def _permissive_dict_value(ann: Any) -> Any:
    args = getattr(ann, "__args__", (str, str))
    v_sample = _permissive_value(args[1]) if len(args) == 2 else "x"
    return {"k": v_sample}


def _is_base_model_type(ann: Any) -> bool:
    return isinstance(ann, type) and issubclass(ann, BaseModel)


def _permissive_value(ann: Any) -> Any:
    """A value that satisfies most annotations without raising during sampling."""
    if getattr(ann, "__origin__", None) in (dict,):
        return _permissive_dict_value(ann)
    if _is_base_model_type(ann):
        return _sample_base_model(ann)
    if ann is bool:
        return True
    if ann in (int, float):
        return 0
    return "x"


def _extract_rootmodel_inner_type(ann: type) -> Any | None:
    fields = list(ann.model_fields.items())
    if len(fields) == 1 and fields[0][0] in ("root", "__root__"):
        return _container_value_type(fields[0][1].annotation)
    return None


def _extract_dict_value_type(ann: Any) -> Any | None:
    args = getattr(ann, "__args__", (str, str))
    if len(args) == 2:
        v = args[1]
        if _is_base_model_type(v):
            return v
    return None


def _container_value_type(ann: Any) -> Any | None:
    """If ``ann`` is ``DictMap[X]`` / ``dict[..., X]`` (X a BaseModel), return X."""
    if _is_base_model_type(ann):
        return _extract_rootmodel_inner_type(ann)
    if getattr(ann, "__origin__", None) in (dict,):
        return _extract_dict_value_type(ann)
    return None


def _root_model_flavor(ann: type) -> bool:
    return "root" in ann.model_fields or "__root__" in ann.model_fields


def _is_primitive_wide(ann: Any) -> bool:
    return ann is str or ann is object or ann is None


def _is_root_model_wide(ann: type) -> bool:
    if not _root_model_flavor(ann):
        return False
    root_field = ann.model_fields.get("root") or ann.model_fields.get("__root__")
    if root_field is not None:
        return _container_is_wide(root_field.annotation)
    return False


def _is_plain_dict_wide(ann: Any) -> bool:
    args = getattr(ann, "__args__", (str, str))
    return len(args) == 2 and args[1] in (str, object, None)


def _container_is_wide(ann: Any) -> bool:
    """True if the container's declared value type is str / Any / object.

    Handles plain ``dict[str, str]`` and ``DictMap[str]`` (a RootModel whose
    single ``root`` field is ``dict[str, str]``).
    """
    if _is_primitive_wide(ann):
        return True
    if _is_base_model_type(ann):
        return _is_root_model_wide(ann)
    if getattr(ann, "__origin__", None) in (dict,):
        return _is_plain_dict_wide(ann)
    return False


def _narrow_container_intent(
    ann: Any, field_name: str, file_models: dict[str, type]
) -> type | None:
    """BUG 2 heuristic: if the container's *type* name is ``<X>Map`` and a
    same-file model ``X`` exists, and the container's declared value type is
    wide (str/Any), return ``X`` as the *intended* value type so the caller can
    check whether the container actually accepts an ``X`` instance.
    """
    if not _container_is_wide(ann):
        return None
    type_name = getattr(ann, "__name__", "") or ""
    if not type_name.endswith("Map"):
        return None
    candidate = type_name[: -len("Map")]
    return file_models.get(candidate)


def _find_source_root(path: Path) -> tuple[str, str] | None:
    s = str(path.as_posix())
    source_root = os.getenv("KIT_SOURCE_ROOT", "src")
    for marker in (f"/{source_root}/", "/src/"):
        idx = s.find(marker)
        if idx != -1:
            rel = s[idx + 1 :].removesuffix(".py").replace("/", ".")
            return str(Path(s[:idx])), rel
    return None


def _module_dotted(path: Path) -> str | None:
    """If ``path`` lives under a package root (``src/`` or ``src/``), return its
    dotted module name (e.g. ``src.interfaces.telegram.session``). Returns
    ``None`` when no such marker is present.
    """
    res = _find_source_root(path)
    return res[1] if res else None


def _import_dotted(root: str, dotted: str) -> tuple[types.ModuleType | None, str | None]:
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        return (importlib.import_module(dotted), None)
    except _ENV_ERRORS as e:
        # Environmental: do not block the coder.
        return (None, f"__ENV_SKIP__:{e}")
    except (ImportError, ModuleNotFoundError, AttributeError, SyntaxError) as e:
        return (None, f"Import failed: {type(e).__name__}: {e}")


def _load_module_dotted(path: Path) -> tuple[types.ModuleType | None, str | None]:
    """Import ``path`` by its dotted package name (so cross-module relative
    imports resolve — 00_fix Fix A'/H). Returns (module, error_message).
    """
    res = _find_source_root(path)
    if res is None:
        return (None, None)
    return _import_dotted(res[0], res[1])


def _setup_sys_path() -> None:
    for p in (str(PROJECT_ROOT), str(PROJECT_ROOT / os.getenv("KIT_SOURCE_ROOT", "src"))):
        if p not in sys.path:
            sys.path.insert(0, p)


def _load_fallback(path: Path) -> tuple[types.ModuleType | None, str | None, str | None]:
    mod_name = f"_smoke_{path.stem}"
    spec = importlib.util.spec_from_file_location(mod_name, str(path))
    if spec is None or spec.loader is None:
        return (None, None, f"Cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
        return module, mod_name, None
    except _ENV_ERRORS as e:
        return (None, None, f"smoke skipped (environmental import error): {e}")
    except (ImportError, ModuleNotFoundError, SyntaxError, AttributeError) as e:
        return (None, None, f"Import failed: {type(e).__name__}: {e}")


def _resolve_module_import(path: Path) -> tuple[types.ModuleType | None, str | None, str | None]:
    loaded, err = _load_module_dotted(path)
    if loaded is not None:
        return loaded, loaded.__name__, None
    if err is not None and err.startswith("__ENV_SKIP__"):
        return None, None, f"smoke skipped (environmental import error): {err[len('__ENV_SKIP__:'):]}"
    return _load_fallback(path)


def _is_target_basemodel(attr: Any, mod_name: str) -> bool:
    if not isinstance(attr, type):
        return False
    if not issubclass(attr, BaseModel):
        return False
    return getattr(attr, "__module__", None) == mod_name


def _extract_defined_basemodels(module: types.ModuleType, mod_name: str) -> list[type]:
    return [
        attr for attr in vars(module).values()
        if _is_target_basemodel(attr, mod_name)
    ]


def _build_permissive_base(cls: type) -> tuple[dict[str, Any], bool]:
    base: dict[str, Any] = {}
    for name, field in cls.model_fields.items():
        base[name] = _permissive_value(field.annotation)
    try:
        cls.model_validate(base)
        return base, True
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return base, False


def _probe_single_container_field(cls: type, base: dict[str, Any], name: str, vtype: type) -> list[str]:
    from pydantic import ValidationError

    sample = _sample_base_model(vtype)
    try:
        cls.model_validate({**base, name: {"k": sample}})
        return []
    except ValidationError as e:
        return [f"{cls.__name__}.{name}: container rejects {vtype.__name__} instance — {e}"]
    except (TypeError, ValueError, AttributeError) as e:
        return [f"{cls.__name__}.{name}: probe error {type(e).__name__}: {e}"]


def _probe_heuristic_fields(
    cls: type, base: dict[str, Any], name: str, annotation: Any, file_models: dict[str, type]
) -> list[str]:
    from pydantic import ValidationError

    heuristic = _narrow_container_intent(annotation, name, file_models)
    if heuristic is None:
        return []
    sample = _sample_base_model(heuristic)
    try:
        cls.model_validate({**base, name: {"k": sample}})
        return []
    except ValidationError as e:
        return [
            (f"{cls.__name__}.{name}: declared container rejects "
            f"{heuristic.__name__} instance (likely wrong value type: "
            f"should be DictMap[{heuristic.__name__}]) — {e}")
        ]
    except (TypeError, ValueError, AttributeError) as e:
        return [f"{cls.__name__}.{name}: probe error {type(e).__name__}: {e}"]


def _probe_container_fields(cls: type, base: dict[str, Any], file_models: dict[str, type]) -> list[str]:
    errors: list[str] = []
    for name, field in cls.model_fields.items():
        vtype = _container_value_type(field.annotation)
        if vtype is not None:
            errors.extend(_probe_single_container_field(cls, base, name, vtype))
        else:
            errors.extend(_probe_heuristic_fields(cls, base, name, field.annotation, file_models))
    return errors


def _probe_all_models(defined_here: list[type], file_models: dict[str, type]) -> list[str]:
    errors: list[str] = []
    for cls in defined_here:
        base, ok = _build_permissive_base(cls)
        if ok:
            errors.extend(_probe_container_fields(cls, base, file_models))
    return errors


def _check_import_error(err: str | None, path: Path) -> tuple[bool, str]:
    if err and err.startswith("smoke skipped"):
        return (True, err)
    return (False, err or f"Cannot load module from {path}")


def _process_module(module: types.ModuleType, mod_name: str, path: Path) -> tuple[bool, str]:
    defined_here = _extract_defined_basemodels(module, mod_name)
    if not defined_here:
        return (True, f"no pydantic models defined in {path.name}")

    file_models = {m.__name__: m for m in defined_here}
    errors = _probe_all_models(defined_here, file_models)

    if errors:
        return (False, "\n".join(errors))
    return (True, f"ok: {len(defined_here)} model(s) probed, no container value-type bugs")


def _do_smoke_module(path: Path) -> tuple[bool, str]:
    _setup_sys_path()
    module, mod_name, err = _resolve_module_import(path)
    if module is None or mod_name is None:
        return _check_import_error(err, path)
    return _process_module(module, mod_name, path)


def smoke_module(file_path: str) -> tuple[bool, str]:
    """Probe every BaseModel subclass defined in the file for container value-type bugs.

    Returns (ok, message). On any container value-type mismatch, ok=False.
    """
    path = Path(file_path).resolve()
    if not path.exists():
        return (False, f"File not found: {path}")
    return _do_smoke_module(path)


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"success": False, "error": "usage: smoke_test.py <file>"}))
        return 2
    ok, msg = smoke_module(sys.argv[1])
    print(json.dumps({"success": ok, "message": msg}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())