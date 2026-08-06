from __future__ import annotations

from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..demo_assets import (
    build_demo_glb,
    demo_poster_url,
    get_model_template,
    select_model_template,
    template_floor_payload,
    template_hotspot_payload,
)
from ..models import (
    CaptureSession,
    Property,
    PropertyFloor,
    PropertyHotspot,
    PropertyModel3D,
    ReconstructionArtifact,
    ReconstructionJob,
)
from ..models.common import new_id
from .reconstruction_backends import FixtureBackend, ReconstructionResult

_PATCHED = False
_HOOK_REGISTERED = False
_JOB_CONTEXT: dict[str, tuple[str, str | None]] = {}


def _context_for_capture(
    session: Session,
    capture: CaptureSession | None,
) -> tuple[str, str | None]:
    prop = session.get(Property, capture.property_id) if capture else None
    if not prop:
        return "apartment-2br", None
    return (
        select_model_template(prop.property_type, prop.bedrooms, prop.floors_count),
        prop.id,
    )


def _persist_job_context(session: Session, job: ReconstructionJob) -> None:
    if not job.id:
        job.id = new_id()
    capture = session.get(CaptureSession, job.session_id)
    template_id, property_id = _context_for_capture(session, capture)
    checkpoint = dict(job.checkpoint_json or {})
    checkpoint.update(
        {
            "fixture_template_id": template_id,
            "fixture_property_id": property_id,
        }
    )
    job.checkpoint_json = checkpoint
    _JOB_CONTEXT[job.id] = (template_id, property_id)


def _template_for_job(job_id: str) -> tuple[str, str | None]:
    cached = _JOB_CONTEXT.get(job_id)
    if cached:
        return cached
    try:
        with SessionLocal() as db:
            job = db.get(ReconstructionJob, job_id)
            checkpoint = dict(job.checkpoint_json or {}) if job else {}
            template_id = checkpoint.get("fixture_template_id")
            property_id = checkpoint.get("fixture_property_id")
            if template_id:
                return str(template_id), str(property_id) if property_id else None
            capture = db.get(CaptureSession, job.session_id) if job else None
            return _context_for_capture(db, capture)
    except SQLAlchemyError:
        # A separate SessionLocal cannot see a SQLite in-memory test database.
        # The normal test path is served by _JOB_CONTEXT populated before flush.
        return "apartment-2br", None


def _fixture_run(
    self: FixtureBackend,
    *,
    job_id: str,
    inputs: list,
    representation: str,
    progress,
) -> ReconstructionResult:
    root = self.settings.reconstruction_work_path.resolve()
    root.mkdir(parents=True, exist_ok=True)
    work = (root / job_id).resolve()
    if work == root or root not in work.parents:
        raise ValueError("Invalid reconstruction work path")
    if work.exists():
        import shutil

        shutil.rmtree(work)
    work.mkdir(parents=True)

    template_id, property_id = _template_for_job(job_id)
    progress("quality_check", 15, {"file_count": len(inputs), "backend": self.name})
    progress("camera_reconstruction", 40, {"fixture": True, "template_id": template_id})
    progress("dense_reconstruction", 65, {"fixture": True, "template_id": template_id})
    progress("optimization", 80, {"fixture": True, "template_id": template_id})

    if representation == "gaussian_splat":
        output = work / f"{job_id}.ply"
        output.write_text(
            "ply\nformat ascii 1.0\nelement vertex 4\n"
            "property float x\nproperty float y\nproperty float z\nend_header\n"
            "-1 0 -1\n1 0 -1\n1 0 1\n-1 0 1\n",
            encoding="utf-8",
        )
        asset_type = "gaussian_splat"
    else:
        output = work / f"{job_id}.glb"
        output.write_bytes(build_demo_glb(template_id))
        asset_type = "glb"

    progress("preview", 92, {"fixture": True, "template_id": template_id})
    template = get_model_template(template_id)
    return ReconstructionResult(
        output,
        asset_type,
        {
            "pipeline": "fixture",
            "input_count": len(inputs),
            "template_id": template_id,
            "default_camera": template.get("camera") or {},
            "file_size_bytes": output.stat().st_size,
            "property_id": property_id,
        },
    )


def _sync_property_model(session: Session, artifact: ReconstructionArtifact) -> None:
    metadata = dict(artifact.metadata_json or {})
    if metadata.get("property_model_synced"):
        return
    job = session.get(ReconstructionJob, artifact.job_id)
    capture = session.get(CaptureSession, job.session_id) if job else None
    prop = session.get(Property, capture.property_id) if capture else None
    if not prop:
        return
    if artifact.asset_type != "glb" and not str(artifact.url).lower().endswith(".glb"):
        return

    template_id = str(
        metadata.get("template_id")
        or select_model_template(prop.property_type, prop.bedrooms, prop.floors_count)
    )
    template = get_model_template(template_id)
    model = prop.model_3d
    if not model:
        model = PropertyModel3D(property_id=prop.id, model_url=artifact.url)
        prop.model_3d = model
    model.model_url = artifact.url
    model.poster_url = demo_poster_url(template_id)
    model.format = "glb"
    model.file_size_bytes = int(metadata.get("file_size_bytes") or 0) or None
    model.draco_compressed = False
    model.meshopt_compressed = False
    model.ktx2_textures = False
    model.default_camera = dict(
        metadata.get("default_camera") or template.get("camera") or {}
    )
    model.quality_presets = {
        "low": {"dpr": 1},
        "medium": {"dpr": 1.5},
        "high": {"dpr": 2},
        "template_id": template_id,
        "source_artifact_id": artifact.id,
        "fixture": metadata.get("pipeline") == "fixture",
    }
    model.processing_status = "ready"
    model.hotspots.clear()
    model.floors.clear()

    floors: list[PropertyFloor] = []
    for row in template_floor_payload(template_id):
        floor = PropertyFloor(
            id=new_id(),
            name=row["name"],
            sort_order=int(row["sort_order"]),
            object_names=list(row["object_names"]),
            furniture_object_names=list(row["furniture_object_names"]),
            camera=dict(row["camera"]),
        )
        model.floors.append(floor)
        floors.append(floor)
    for hotspot_row in template_hotspot_payload(template_id):
        row = dict(hotspot_row)
        floor_index = min(int(row.pop("floor_index")), len(floors) - 1)
        model.hotspots.append(
            PropertyHotspot(
                id=new_id(),
                floor_id=floors[floor_index].id if floors else None,
                label=row["label"],
                description=row.get("description"),
                position=list(row["position"]),
                camera_position=list(row["camera_position"]),
                room_type=row.get("room_type"),
                metadata_json=dict(row.get("metadata_json") or {}),
            )
        )
    prop.has_3d = True
    metadata["template_id"] = template_id
    metadata["property_model_synced"] = True
    artifact.metadata_json = metadata


def install_demo_reconstruction_hooks() -> None:
    global _PATCHED, _HOOK_REGISTERED
    if not _PATCHED:
        FixtureBackend.run = _fixture_run  # type: ignore[method-assign]
        _PATCHED = True
    if _HOOK_REGISTERED:
        return

    @event.listens_for(Session, "before_flush")
    def prepare_jobs_and_sync_artifacts(
        session: Session,
        _flush_context: Any,
        _instances: Any,
    ) -> None:
        for item in list(session.new):
            if isinstance(item, ReconstructionJob):
                _persist_job_context(session, item)
        for item in list(session.dirty):
            if not isinstance(item, ReconstructionArtifact) or not item.published:
                continue
            state = inspect(item)
            published_changed = state.attrs.published.history.has_changes()
            metadata = item.metadata_json or {}
            if published_changed or not metadata.get("property_model_synced"):
                _sync_property_model(session, item)

    _HOOK_REGISTERED = True
