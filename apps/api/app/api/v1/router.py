from fastapi import APIRouter

from app.api.v1 import ai, ask, github, health, indexing, me, orgs, repos, teams, webhooks

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(me.router)
api_router.include_router(orgs.router)
api_router.include_router(teams.router)
api_router.include_router(ai.router)
api_router.include_router(ask.router)
api_router.include_router(github.router)
api_router.include_router(indexing.router)
api_router.include_router(repos.router)
api_router.include_router(webhooks.router)
