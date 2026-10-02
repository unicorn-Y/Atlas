"""Loopback-only scripted OpenAI fake; never forwards to an upstream."""
from .server import FaultProxy

__all__ = ["FaultProxy"]
