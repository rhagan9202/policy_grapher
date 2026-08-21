"""Request-scoped access to state the lifespan puts on the app."""

from fastapi import Request
from neo4j import Driver

from policy_grapher.config import Settings
from policy_grapher.embedding import Embedder


def get_driver(request: Request) -> Driver:
    return request.app.state.driver


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_embedder(request: Request) -> Embedder:
    """The embedder `lifespan` resolved. Built once at boot so an unknown adapter
    name fails there, and so a local model is loaded at most once per process."""
    return request.app.state.embedder
