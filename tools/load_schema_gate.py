import argparse
import importlib.util
import os
import sys
from pathlib import Path

from pydantic import BaseModel

from control import REPO_ROOT


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("file_path", help="Path to the staged python file")
    return parser.parse_args()


def setup_path(repo_root, temp_dir):
    sys.path.insert(0, str(temp_dir))
    if str(repo_root) not in sys.path:
        sys.path.insert(1, str(repo_root))


def resolve_relative_path(fp, temp_dir, repo_root):
    try:
        rel = fp.relative_to(temp_dir)
    except ValueError:
        try:
            rel = fp.relative_to(repo_root)
        except ValueError:
            print(f"File {fp} is not in repo.")
            sys.exit(1)
    return rel


def build_module_name(rel):
    return (
        "schema_gate_" + str(rel.with_suffix("")).replace(os.sep, "_").replace(".", "_")
    )


def load_module(fp, module_name):
    try:
        spec = importlib.util.spec_from_file_location(module_name, str(fp))
        if spec is None or spec.loader is None:
            print(f"Failed to load {fp}: could not build import spec")
            sys.exit(1)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    except (ImportError, SyntaxError, AttributeError, TypeError, ValueError) as e:
        print(f"Failed to import {module_name}: {type(e).__name__}: {e}")
        sys.exit(1)


def validate_model_schema(name, obj):
    try:
        obj.model_json_schema()
    except (ValueError, TypeError) as e:
        print(f"Failed schema validation for {name}: {type(e).__name__}: {e}")
        sys.exit(1)


def validate_schemas(module):
    for name in dir(module):
        obj = getattr(module, name)
        if isinstance(obj, type) and issubclass(obj, BaseModel) and obj is not BaseModel:
            validate_model_schema(name, obj)


def main():
    args = parse_args()
    repo_root = REPO_ROOT
    temp_dir = repo_root / os.getenv("KIT_TEMP_DIR", "temp")
    setup_path(repo_root, temp_dir)
    fp = Path(args.file_path).resolve()
    rel = resolve_relative_path(fp, temp_dir, repo_root)
    module_name = build_module_name(rel)
    module = load_module(fp, module_name)
    validate_schemas(module)
    print("Schema load successful.")
    sys.exit(0)


if __name__ == "__main__":
    main()
