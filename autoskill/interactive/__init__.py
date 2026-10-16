"""
Interactive module.

This package contains the interactive "chat + optional extract" loop.
It is designed as a reusable module (not only as an example script).
"""

from .app import InteractiveChatApp
from .config import InteractiveConfig
from .io import ConsoleIO, IO
from .server import AutoSkillProxyConfig, AutoSkillProxyRuntime
from .unified import AutoSkillRuntime

__all__ = [
    "AutoSkillProxyConfig",
    "AutoSkillProxyRuntime",
    "AutoSkillRuntime",
    "ConsoleIO",
    "IO",
    "InteractiveChatApp",
    "InteractiveConfig",
]
