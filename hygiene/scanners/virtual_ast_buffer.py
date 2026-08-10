"""
Virtual AST Staging Buffer for In-Memory AST Transformations.

Provides AST-based function replacement, helper function deduplication,
and transactional rollback stack without mutating live files on disk.
"""

import ast
import copy
from collections.abc import Callable

__all__ = [
    "FunctionReplacer",
    "VirtualASTBuffer",
    "ensure_pydantic_imports",
    "verify_class_structure_intact",
]


class FunctionReplacer(ast.NodeTransformer):
    """Replaces a target function node in the AST with new AST nodes."""

    def __init__(self, target_name: str, new_nodes: list[ast.AST]) -> None:
        self.target_name = target_name
        self.new_nodes = new_nodes
        self.replaced = False

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST | list[ast.AST]:
        if node.name == self.target_name:
            self.replaced = True
            if len(self.new_nodes) == 1:
                return self.new_nodes[0]
            return self.new_nodes
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST | list[ast.AST]:
        if node.name == self.target_name:
            self.replaced = True
            if len(self.new_nodes) == 1:
                return self.new_nodes[0]
            return self.new_nodes
        return self.generic_visit(node)


class VirtualASTBuffer:
    """
    In-memory AST staging buffer for python modules.
    Tracks module AST modifications and maintains a rollback stack.
    """

    def __init__(self, source_code: str, file_path: str = "") -> None:
        self.file_path = file_path
        self.source_code = source_code
        self.tree: ast.Module = ast.parse(source_code)
        self.snapshots: list[ast.Module] = []
        self._inserted_helpers: set[str] = set()

    def push_checkpoint(self) -> None:
        """Pushes current tree state onto the snapshot stack."""
        self.snapshots.append(copy.deepcopy(self.tree))

    def pop_checkpoint(self) -> bool:
        """Discards top snapshot without restoring. Returns True if stack was non-empty."""
        if self.snapshots:
            self.snapshots.pop()
            return True
        return False

    def rollback(self) -> bool:
        """Restores tree to the previous snapshot state. Returns True if restored."""
        if self.snapshots:
            self.tree = self.snapshots.pop()
            self._inserted_helpers = {
                n.name
                for n in self.tree.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in self._inserted_helpers
            }
            return True
        return False

    def get_source(self) -> str:
        """Returns the unparsed Python source code from the current AST tree."""
        return ast.unparse(self.tree)

    def replace_function(
        self,
        target_name: str,
        refactored_code: str,
        helper_codes: list[str] | None = None,
    ) -> str:
        """
        Replaces target_name function with refactored_code AST node(s).
        Inserts or replaces helper functions by name in top-level module body.
        Returns the unparsed Python source code string.
        """
        refactored_tree = ast.parse(refactored_code)
        new_func_nodes: list[ast.AST] = []
        for stmt in refactored_tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                new_func_nodes.append(stmt)
                if stmt.name != target_name:
                    for node in self.tree.body:
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            if node.name == stmt.name and node.name != target_name and node.name not in self._inserted_helpers:
                                raise ValueError(
                                    f"helper_collision: Collision: helper function name '{stmt.name}' already exists in target module {self.file_path}"
                                )

        if not new_func_nodes:
            raise ValueError(f"No valid function definition found in refactored_code for `{target_name}`")

        replacer = FunctionReplacer(target_name, new_func_nodes)
        self.tree = replacer.visit(self.tree)
        ast.fix_missing_locations(self.tree)

        if helper_codes:
            self._upsert_helpers(helper_codes, target_name=target_name)

        return self.get_source()

    def _upsert_helpers(
        self,
        helper_codes: list[str],
        target_name: str | None = None,
    ) -> None:
        """Upserts (replaces existing or appends new) helper functions in top-level module body."""
        for h_code in helper_codes:
            if not h_code.strip():
                continue
            h_tree = ast.parse(h_code)
            for stmt in h_tree.body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    h_name = stmt.name
                    # Check for helper collisions with pre-existing module function/class
                    for node in self.tree.body:
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            if node.name == h_name:
                                if node.name != target_name and node.name not in self._inserted_helpers:
                                    raise ValueError(
                                        f"helper_collision: Collision: helper function name '{stmt.name}' already exists in target module {self.file_path}"
                                    )

                    # Check if helper function already exists in module body
                    replaced = False
                    for i, node in enumerate(self.tree.body):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == h_name:
                            self.tree.body[i] = stmt
                            replaced = True
                            break
                    if not replaced:
                        self.tree.body.append(stmt)
                    self._inserted_helpers.add(h_name)
                    ast.fix_missing_locations(self.tree)


def verify_class_structure_intact(original_code: str, modified_code: str) -> bool:
    """Verifies that all (class_name, method_name) pairs from original_code still exist in modified_code."""
    try:
        orig_tree = ast.parse(original_code)
        mod_tree = ast.parse(modified_code)
        orig_methods = set()
        for node in ast.walk(orig_tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        orig_methods.add((node.name, item.name))
        mod_methods = set()
        for node in ast.walk(mod_tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        mod_methods.add((node.name, item.name))
        for cls_name, method_name in orig_methods:
            if (cls_name, method_name) not in mod_methods:
                return False
        return True
    except (AttributeError, TypeError, SyntaxError):
        return False  # introspection failure — assume non-conformance


_NEEDED_MODULES: dict[str, str] = {
    "BaseModel": "pydantic",
    "Field": "pydantic",
    "Any": "typing",
}


def _safe_parse(source: str, parser: Callable[[ast.Module, set[str]], set[str]], symbols: set[str]) -> dict[str, bool]:
    """Parse source and run `parser`; return dict[str,bool] or all-False on SyntaxError."""
    try:
        tree = ast.parse(source)
        found = parser(tree, symbols)
        return {s: (s in found) for s in symbols}
    except SyntaxError:
        return {s: False for s in symbols}


def _parse_has_imports(tree: ast.Module, symbols: set[str]) -> set[str]:
    """Set of imported symbol names (honoring asname)."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod_map = {"pydantic": ("BaseModel", "Field"), "typing": ("Any",)}
            needed_mods = mod_map.get(node.module or "", ())
            for alias in node.names:
                name = alias.asname or alias.name
                if name in needed_mods and name in symbols:
                    found.add(name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "pydantic":
                    found.update(s for s in ("BaseModel", "Field") if s in symbols)
                elif alias.name == "typing":
                    if "Any" in symbols:
                        found.add("Any")
    return found


def _parse_uses_symbols(tree: ast.Module, symbols: set[str]) -> set[str]:
    """Set of symbol names referenced as Name nodes."""
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id in symbols}


def _find_insert_after_future(lines: list[str]) -> int | None:
    last_idx = -1
    for idx, line in enumerate(lines):
        if line.strip().startswith("from __future__ import"):
            last_idx = idx
    return last_idx + 1 if last_idx != -1 else None


def _find_insert_after_docstring(lines: list[str]) -> int | None:
    in_docstring = False
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if idx == 0 and (stripped.startswith('"""') or stripped.startswith("'''")):
            quote = '"""' if stripped.startswith('"""') else "'''"
            if stripped.count(quote) == 2:
                return 1
            in_docstring = True
            continue
        if in_docstring and ('"""' in stripped or "'''" in stripped):
            return idx + 1
    return None


def _insert_imports(source: str, needed: list[str]) -> str:
    """Insert `from <module> import ...` lines after __future__/docstring."""
    import_lines = [
        f"from {mod} import {sym}"
        for sym in needed
        if (mod := _NEEDED_MODULES.get(sym))
    ]
    import_block = "\n".join(import_lines) + "\n"
    lines = source.splitlines(keepends=True)

    after_future = _find_insert_after_future(lines)
    if after_future is not None:
        lines.insert(after_future, import_block)
        return "".join(lines)

    after_doc = _find_insert_after_docstring(lines)
    if after_doc is not None:
        lines.insert(after_doc, import_block)
        return "".join(lines)

    insert_idx = 0
    for idx, line in enumerate(lines):
        if line.strip() and not line.strip().startswith("#"):
            insert_idx = idx
            break
    lines.insert(insert_idx, import_block)
    return "".join(lines)


def ensure_pydantic_imports(source: str, ref_code: str) -> str:
    """Ensures BaseModel, Field, and Any imports exist in source if ref_code uses them.
    Intelligently places new imports after __future__ imports or module docstrings."""
    target_symbols = {"BaseModel", "Field", "Any"}

    has_imports = _safe_parse(source, _parse_has_imports, target_symbols)
    uses_symbols = _safe_parse(ref_code, _parse_uses_symbols, target_symbols)

    needed = [s for s in target_symbols if uses_symbols.get(s, False) and not has_imports.get(s, False)]
    if not needed:
        return source
    return _insert_imports(source, needed)

