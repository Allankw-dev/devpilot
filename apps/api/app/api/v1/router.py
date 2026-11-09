from fastapi import APIRouter

from app.api.v1 import github, health, me, orgs, repos, teams, webhooks

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(me.router)
api_router.include_router(orgs.router)
api_router.include_router(teams.router)
api_router.include_router(github.router)
api_router.include_router(repos.router)
api_router.include_router(webhooks.router)
