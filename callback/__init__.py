"""
Callback System для MikoPBX
Модуль обратного звонка для пропущенных звонков и голосовой почты
"""

from .manager import CallbackManager
from .config import CallbackConfig
from .ami_connector import AMIConnector

__version__ = "1.0.0"
__all__ = ['CallbackManager', 'CallbackConfig', 'AMIConnector']
