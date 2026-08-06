"""书架总大脑：书级写作助手，读取全书上下文 + Skills，可提案并执行动作。"""

from .brain import build_context, chat, execute_action

__all__ = ["build_context", "chat", "execute_action"]
