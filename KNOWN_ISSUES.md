
## Python 3.14 + FastAPI shutdown RecursionError

**现象**: 服务收到 SIGTERM 时出现 `RecursionError: maximum recursion depth exceeded`  
**路径**: `jsonable_encoder → is_pydantic_v1_model_instance → warnings.simplefilter → _add_filter`  
**影响**: 仅 shutdown 时出现，不影响运行时稳定性。新服务启动正常。  
**根因**: Python 3.14 warnings 模块与 FastAPI pydantic 兼容检查交互问题  
**缓解**: 可升级 FastAPI 至 Python 3.14 正式支持版本后修复  
**发现**: 2026-07-08, v3.115.16

