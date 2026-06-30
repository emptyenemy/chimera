"""Выборочный прокси через sing-box: домены из наших списков -> VLESS, остальное напрямую."""

from .manager import ProxyManager

__all__ = ["ProxyManager"]
