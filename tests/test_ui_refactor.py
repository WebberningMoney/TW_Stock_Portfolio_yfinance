"""不啟動 Tk、也不連線 Yahoo 的 UI 架構測試。"""

import ast
from pathlib import Path


def test_refactor_method_surface() -> None:
    root = Path(__file__).resolve().parents[1]
    python_files = [root / 'app/ui/main_window.py']
    python_files.extend((root / 'app/ui/mixins').glob('*.py'))

    method_names: set[str] = set()
    for path in python_files:
        module = ast.parse(path.read_text(encoding='utf-8'))
        for node in module.body:
            if isinstance(node, ast.ClassDef):
                method_names.update(
                    child.name
                    for child in node.body
                    if isinstance(child, ast.FunctionDef)
                )

    required = {
        '_build_layout',
        'refresh_holding_view',
        'refresh_dividend_view',
        'refresh_loaded_data_view',
        'sync_actions_async',
        '_build_ai_sidebar',
        'confirm_save_holding',
        '_sort_treeview',
        '_bind_global_shortcuts',
    }
    assert required.issubset(method_names)
