import importlib
import inspect
import pkgutil

import src
from pydantic import BaseModel, RootModel


def get_all_pydantic_models() -> list[type[BaseModel]]:
    models: list[type[BaseModel]] = []
    src_dir = str(src.__path__[0])
    seen: set[str] = set()

    for importer, modname, ispkg in pkgutil.walk_packages(
        src.__path__, src.__name__ + "."
    ):
        try:
            mod = importlib.import_module(modname)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            continue

        mod_file = getattr(mod, "__file__", None)
        if not mod_file or not mod_file.startswith(src_dir):
            continue

        for name, obj in inspect.getmembers(mod, inspect.isclass):
            if not issubclass(obj, BaseModel) or obj is BaseModel:
                continue
            if getattr(obj, "__module__", None) != modname:
                continue
            key = f"{modname}.{name}"
            if key in seen:
                continue
            seen.add(key)
            models.append(obj)

    return models


def test_all_pydantic_models_enforce_extra_forbid():
    models = get_all_pydantic_models()
    violating = [
        m.__name__
        for m in models
        if not issubclass(m, RootModel)
        and m.model_config.get("extra") != "forbid"
    ]
    assert not violating, f"Models not enforcing extra='forbid': {violating}"


def test_all_pydantic_models_enforce_validate_assignment():
    models = get_all_pydantic_models()
    violating = [
        m.__name__
        for m in models
        if m.model_config.get("validate_assignment") is not True
    ]
    assert not violating, (
        f"Models not enforcing validate_assignment=True: {violating}"
    )


def test_all_pydantic_models_strict_mode():
    models = get_all_pydantic_models()
    violations = []
    for m in models:
        config = m.model_config
        extra = config.get("extra")
        va = config.get("validate_assignment")
        is_root_model = issubclass(m, RootModel)
        if not is_root_model and extra != "forbid":
            violations.append(f"{m.__module__}.{m.__name__} (extra={extra!r})")
        if va is not True:
            violations.append(f"{m.__module__}.{m.__name__} (validate_assignment={va!r})")
    assert not violations, (
        "Models with strict mode violations:\n" + "\n".join(violations)
    )
