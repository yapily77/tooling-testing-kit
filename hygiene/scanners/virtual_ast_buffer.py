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

    def visit_AsyncFunctionDef(
        self, node: ast.AsyncFunctionDef
    ) -> ast.AST | list[ast.AST]:
        if node.name == self.target_name:
            self.replaced = True
            if len(self.new_nodes) == 1:
                return self.new_nodes[0]
            return self.new_nodes
        return self.generic_visit(node)


def _check_helper_collision(
    tree: ast.Module,
    h_name: str,
    target_name: str | None,
    inserted_helpers: set[str],
    file_path: str,
) -> None:
    """Raises ValueError if `h_name` collides with a pre-existing module function/class."""
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if node.name in (target_name, *inserted_helpers):
            continue
        if node.name == h_name:
            raise ValueError(
                f"helper_collision: Collision: helper function name '{h_name}' already exists in target module {file_path}"
            )


def _insert_or_replace_helper(
    tree: ast.Module,
    stmt: ast.FunctionDef | ast.AsyncFunctionDef,
    inserted_helpers: set[str],
) -> None:
    """Inserts `stmt` if absent, replaces it in-place if present, updates tracking set."""
    h_name = stmt.name
    replaced = False
    for i, node in enumerate(tree.body):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == h_name
        ):
            tree.body[i] = stmt
            replaced = True
            break
    if not replaced:
        tree.body.append(stmt)
    inserted_helpers.add(h_name)
    ast.fix_missing_locations(tree)


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
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name in self._inserted_helpers
            }
            return True
        return False

    def get_source(self) -> str:
        """Returns the unparsed Python source code from the current AST tree."""
        return ast.unparse(self.tree)

    def _validate_new_func_nodes(
        self, refactored_tree: ast.Module, target_name: str
    ) -> list[ast.AST]:
        """Parses refactored_tree and validates helper collisions. Returns list of function nodes."""
        new_func_nodes: list[ast.AST] = []
        for stmt in refactored_tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                new_func_nodes.append(stmt)
                _check_helper_collision(
                    self.tree,
                    stmt.name,
                    target_name,
                    self._inserted_helpers,
                    self.file_path,
                )
        if not new_func_nodes:
            raise ValueError(
                f"No valid function definition found in refactored_code for `{target_name}`"
            )
        return new_func_nodes

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
                    _check_helper_collision(
                        self.tree,
                        stmt.name,
                        target_name,
                        self._inserted_helpers,
                        self.file_path,
                    )
                    _insert_or_replace_helper(self.tree, stmt, self._inserted_helpers)

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
        new_func_nodes = self._validate_new_func_nodes(refactored_tree, target_name)

        replacer = FunctionReplacer(target_name, new_func_nodes)
        self.tree = replacer.visit(self.tree)
        ast.fix_missing_locations(self.tree)

        if helper_codes:
            self._upsert_helpers(helper_codes, target_name=target_name)

        return self.get_source()


def _collect_class_methods_from_tree(tree: ast.Module) -> set[tuple[str, str]]:
    """Collects all (class_name, method_name) pairs from a parsed module tree."""
    methods: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.add((node.name, item.name))
    return methods


def verify_class_structure_intact(original_code: str, modified_code: str) -> bool:
    """Verifies that all (class_name, method_name) pairs from original_code still exist in modified_code."""
    try:
        orig_tree = ast.parse(original_code)
        mod_tree = ast.parse(modified_code)
        orig_methods = _collect_class_methods_from_tree(orig_tree)
        mod_methods = _collect_class_methods_from_tree(mod_tree)
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


def _safe_parse(
    source: str, parser: Callable[[ast.Module, set[str]], set[str]], symbols: set[str]
) -> dict[str, bool]:
    """Parse source and run `parser`; return dict[str,bool] or all-False on SyntaxError."""
    try:
        tree = ast.parse(source)
        found = parser(tree, symbols)
        return {s: (s in found) for s in symbols}
    except SyntaxError:
        return {s: False for s in symbols}


def _match_import_from_alias(
    alias: ast.alias, needed_mods: tuple[str, ...], symbols: set[str]
) -> set[str]:
    """Returns matching symbol name for a single alias if it matches needed mods and symbols."""
    name = alias.asname or alias.name
    if name in needed_mods and name in symbols:
        return {name}
    return set()


def _check_import_from_node(node: ast.ImportFrom, symbols: set[str]) -> set[str]:
    """Checks an ImportFrom node for needed module symbols."""
    found: set[str] = set()
    mod_map = {"pydantic": ("BaseModel", "Field"), "typing": ("Any",)}
    needed_mods = mod_map.get(node.module or "", ())
    for alias in node.names:
        found.update(_match_import_from_alias(alias, needed_mods, symbols))
    return found


def _match_pydantic_alias(alias: ast.alias, symbols: set[str]) -> set[str]:
    """Returns matching pydantic symbols for an alias importing `pydantic`."""
    if alias.name == "pydantic":
        return {s for s in ("BaseModel", "Field") if s in symbols}
    return set()


def _match_typing_alias(alias: ast.alias, symbols: set[str]) -> set[str]:
    """Returns matching typing symbols for an alias importing `typing`."""
    if alias.name == "typing" and "Any" in symbols:
        return {"Any"}
    return set()


def _check_import_node(node: ast.Import, symbols: set[str]) -> set[str]:
    """Checks an Import node for needed top-level module symbols."""
    found: set[str] = set()
    for alias in node.names:
        found.update(_match_pydantic_alias(alias, symbols))
        found.update(_match_typing_alias(alias, symbols))
    return found


def _parse_has_imports(tree: ast.Module, symbols: set[str]) -> set[str]:
    """Set of imported symbol names (honoring asname)."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            found.update(_check_import_from_node(node, symbols))
        elif isinstance(node, ast.Import):
            found.update(_check_import_node(node, symbols))
    return found


def _parse_uses_symbols(tree: ast.Module, symbols: set[str]) -> set[str]:
    """Set of symbol names referenced as Name nodes."""
    return {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id in symbols
    }


def _find_insert_after_future(lines: list[str]) -> int | None:
    last_idx = -1
    for idx, line in enumerate(lines):
        if line.strip().startswith("from __future__ import"):
            last_idx = idx
    return last_idx + 1 if last_idx != -1 else None


def _is_module_docstring_first_line(idx: int, stripped: str) -> tuple[str, bool]:
    """Returns (quote_style, is_single_line) if the line starts a module docstring, else ('', False)."""
    if idx == 0 and (stripped.startswith(('"""', "'''"))):
        quote = '"""' if stripped.startswith('"""') else "'''"
        if stripped.count(quote) == 2:
            return (quote, True)
        return (quote, False)
    return ("", False)


def _find_docstring_close_line(lines: list[str], quote: str) -> int | None:
    """Finds the index (1-based) of the line closing a multi-line docstring with the given quote."""
    for idx, line in enumerate(lines):
        if quote in line.strip():
            return idx + 1
    return None


def _check_docstring_close(stripped: str, quote: str) -> bool:
    """Returns True if the stripped line contains the closing quote of a docstring."""
    return quote in stripped


def _handle_docstring_start(idx: int, stripped: str) -> tuple[str, int | None]:
    """Returns (quote, insert_idx) for a docstring-starting line. insert_idx is set if single-line."""
    q, is_single = _is_module_docstring_first_line(idx, stripped)
    if not q:
        return ("", None)
    if is_single:
        return (q, 1)
    return (q, None)


def _find_insert_after_docstring(lines: list[str]) -> int | None:
    quote: str = ""
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not quote:
            quote, single_idx = _handle_docstring_start(idx, stripped)
            if single_idx is not None:
                return single_idx
            continue
        if _check_docstring_close(stripped, quote):
            return idx + 1
    return None


def _resolve_insert_position(lines: list[str]) -> int:
    """Resolves the insert index for the import block when no future/docstring anchor exists."""
    for idx, line in enumerate(lines):
        if line.strip() and not line.strip().startswith("#"):
            return idx
    return 0


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
        return _apply_insert(lines, after_future, import_block)

    after_doc = _find_insert_after_docstring(lines)
    if after_doc is not None:
        return _apply_insert(lines, after_doc, import_block)

    insert_idx = _resolve_insert_position(lines)
    return _apply_insert(lines, insert_idx, import_block)


def _apply_insert(lines: list[str], idx: int, import_block: str) -> str:
    """Inserts import_block at idx and returns the joined source."""
    lines.insert(idx, import_block)
    return "".join(lines)


def ensure_pydantic_imports(source: str, ref_code: str) -> str:
    """Ensures BaseModel, Field, and Any imports exist in source if ref_code uses them.
    Intelligently places new imports after __future__ imports or module docstrings."""
    target_symbols = {"BaseModel", "Field", "Any"}

    has_imports = _safe_parse(source, _parse_has_imports, target_symbols)
    uses_symbols = _safe_parse(ref_code, _parse_uses_symbols, target_symbols)

    needed = [
        s
        for s in target_symbols
        if uses_symbols.get(s, False) and not has_imports.get(s, False)
    ]
    if not needed:
        return source
    return _insert_imports(source, needed)
