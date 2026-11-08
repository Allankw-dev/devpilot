from fastapi import APIRouter

from app.api.v1 import health, me, orgs, teams

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(me.router)
api_router.include_router(orgs.router)
api_router.include_router(teams.router)
