from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from ..database import get_db
from ..models import Agent, Project, Property
from ..schemas import AgentRead, ProjectRead
from ..services.search import property_query_options
from ..services.serializers import property_summary
router = APIRouter(tags=["projects", "agents"])
@router.get("/projects", response_model=list[ProjectRead])
def list_projects(db: Session = Depends(get_db)): return list(db.scalars(select(Project).order_by(Project.name)))
@router.get("/projects/{slug}")
def get_project(slug: str, db: Session = Depends(get_db)):
    project = db.scalar(select(Project).where(Project.slug == slug))
    if not project: raise HTTPException(status_code=404, detail="Project not found")
    properties = list(db.scalars(select(Property).where(Property.project_id == project.id, Property.status == "published").options(*property_query_options())))
    return {"project": ProjectRead.model_validate(project), "properties": [property_summary(x) for x in properties]}
@router.get("/agents", response_model=list[AgentRead])
def list_agents(db: Session = Depends(get_db)): return list(db.scalars(select(Agent).options(selectinload(Agent.agency)).order_by(Agent.verified.desc(), Agent.rating.desc())))
@router.get("/agents/{agent_id}")
def get_agent(agent_id: str, db: Session = Depends(get_db)):
    agent = db.scalar(select(Agent).where(Agent.id == agent_id).options(selectinload(Agent.agency)))
    if not agent: raise HTTPException(status_code=404, detail="Agent not found")
    properties = list(db.scalars(select(Property).where(Property.agent_id == agent.id, Property.status == "published").options(*property_query_options())))
    return {"agent": AgentRead.model_validate(agent), "properties": [property_summary(x) for x in properties]}
