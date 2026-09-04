"""模块导入适配层。

通过 importlib 按文件路径加载模块，支持任意目录名。
用法: load_module("adb_connector", "device") → module
"""

import importlib.util
import os


def load_module(module_name: str, file_name: str):
    """加载 modules/{module_name}/{file_name}.py 并返回模块对象。

    Args:
        module_name: 模块目录名（如 'adb_connector'）
        file_name: Python 文件名（不含 .py，如 'device'）

    Returns:
        加载后的模块对象
    """
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, module_name, f"{file_name}.py")
    spec = importlib.util.spec_from_file_location(
        f"modules.{module_name}.{file_name}", path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# 向后兼容别名
load = load_module
