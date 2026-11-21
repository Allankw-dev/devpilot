from fastapi import APIRouter

from app.api.v1 import (
    ai,
    analytics,
    ask,
    ci,
    conversations,
    dashboard,
    github,
    health,
    indexing,
    issues,
    me,
    orgs,
    repos,
    reviews,
    teams,
    webhooks,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(me.router)
api_router.include_router(orgs.router)
api_router.include_router(teams.router)
api_router.include_router(ai.router)
api_router.include_router(ask.router)
api_router.include_router(github.router)
api_router.include_router(indexing.router)
api_router.include_router(reviews.router)
api_router.include_router(ci.router)
api_router.include_router(conversations.router)
api_router.include_router(analytics.router)
api_router.include_router(issues.router)
api_router.include_router(dashboard.router)
api_router.include_router(repos.router)
api_router.include_router(webhooks.router)
