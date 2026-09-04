"""项目级测试配置 — 确保 modules/ 包可导入。"""

import sys
import os

# 将项目根目录加入 sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
