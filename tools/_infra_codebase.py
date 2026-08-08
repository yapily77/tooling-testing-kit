import importlib
import os
import sys
from pathlib import Path

_infra_root = os.getenv("KIT_INFRA_ROOT", str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(_infra_root).resolve()))

try:
    _mod = importlib.import_module("infra.codebase.mcp_codebase")
    index_repository = _mod.index_repository
    query_knowledge_graph = _mod.query_knowledge_graph
    graph_health = _mod.graph_health
    verify_file_path = _mod.verify_file_path
except ImportError:
    def index_repository(*args, **kwargs):
        return {"success": False, "message": "KIT_INFRA_ROOT not configured or infra.codebase module unavailable"}
    def query_knowledge_graph(*args, **kwargs):
        return {"success": False, "message": "KIT_INFRA_ROOT not configured or infra.codebase module unavailable"}
    def graph_health(*args, **kwargs):
        return {"success": False, "message": "KIT_INFRA_ROOT not configured or infra.codebase module unavailable"}
    def verify_file_path(path: str, *args, **kwargs):
        p = Path(path)
        return {"exists": p.exists(), "path": str(p)}
