"""
/api/projects — list projects, fetch one, list a project's jobs.

Thin router (Rule 2): parse input, call the injected store, return models (which
serialize to camelCase). No business logic lives here.
"""

import logging

from fastapi import APIRouter, Depends

from src.api.dependencies import UserContext, get_container, get_current_user
from src.composition.container import AppContainer
from src.core.errors.app_error import AppError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("")
async def list_projects(
    container: AppContainer = Depends(get_container),
    user: UserContext = Depends(get_current_user),
) -> list:
    """List every project (cross-partition scan; fine at this scale)."""
    return await container.project_store.list_all()


@router.get("/{project_id}")
async def get_project(
    project_id: str,
    container: AppContainer = Depends(get_container),
    user: UserContext = Depends(get_current_user),
):
    """Return one project by id, or a 404-class AppError if missing."""
    project = await container.project_store.get(project_id)
    if project is None:
        raise AppError(
            code="PROJECTS_NOT_FOUND",
            message="No project found for the requested id",
            context={"project_id": project_id},
        )
    return project


@router.get("/{project_id}/jobs")
async def list_project_jobs(
    project_id: str,
    container: AppContainer = Depends(get_container),
    user: UserContext = Depends(get_current_user),
) -> list:
    """List the project's jobs (single-partition query on `/projectId`)."""
    return await container.job_store.list_for_project(project_id)
