"""Request-scoped access to state the lifespan puts on the app."""

from fastapi import Request
from neo4j import Driver

from policy_grapher.config import Settings


def get_driver(request: Request) -> Driver:
    return request.app.state.driver


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings
