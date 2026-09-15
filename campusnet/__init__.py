"""campusnet —— 校园网 Portal 自动登录。

零依赖，只用 Python 标准库。
"""

from .config import Config, default_config_path, load_config  # noqa: F401
from .session import Response, Session  # noqa: F401

__all__ = ["Config", "Session", "Response", "load_config", "default_config_path", "__version__"]

__version__ = "0.1.0"
