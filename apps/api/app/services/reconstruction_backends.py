from __future__ import annotations

import hashlib
import mimetypes
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import urlparse

import httpx

from ..config import Settings, get_settings
from .storage import read_private_bytes


class ReconstructionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReconstructionInput:
    url: str
    sha256: str
    mime_type: str
    size_bytes: int


@dataclass(frozen=True)
class ReconstructionResult:
    output_path: Path
    asset_type: str
    metadata: dict[str, Any] = field(default_factory=dict)
    auxiliary_paths: dict[str, Path] = field(default_factory=dict)


ProgressCallback = Callable[[str, int, dict[str, Any]], None]


class ReconstructionBackend(Protocol):
    name: str

    def run(
        self,
        *,
        job_id: str,
        inputs: list[ReconstructionInput],
        representation: str,
        progress: ProgressCallback,
    ) -> ReconstructionResult: ...


def _safe_work_dir(settings: Settings, job_id: str) -> Path:
    root = settings.reconstruction_work_path.resolve()
    root.mkdir(parents=True, exist_ok=True)
    work = (root / job_id).resolve()
    if work == root or root not in work.parents:
        raise ReconstructionError("Invalid reconstruction work path")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    return work


def _run(command: list[str], *, timeout: int, cwd: Path, log_path: Path) -> None:
    if not command or any(not isinstance(item, str) or not item for item in command):
        raise ReconstructionError("Invalid reconstruction command")
    executable = shutil.which(command[0])
    if not executable:
        raise ReconstructionError(f"Required executable is unavailable: {command[0]}")
    resolved_command = [executable, *command[1:]]
    try:
        completed = subprocess.run(
            resolved_command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ReconstructionError(f"Command timed out: {resolved_command[0]}") from exc
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write("$ " + " ".join(resolved_command) + "\n")
        log.write(completed.stdout[-200_000:] + "\n")
    if completed.returncode != 0:
        raise ReconstructionError(
            f"Command failed ({completed.returncode}): {resolved_command[0]}; see {log_path}"
        )


def _local_storage_source(url: str, settings: Settings) -> Path | None:
    marker = "/storage/"
    storage_root = settings.storage_path.resolve()
    work_root = settings.reconstruction_work_path.resolve()
    if marker in url:
        relative = url.split(marker, 1)[1]
        candidate = (storage_root / relative).resolve()
        if candidate == storage_root or storage_root not in candidate.parents:
            raise ReconstructionError("Capture path escapes storage root")
        return candidate
    candidate = Path(url)
    if candidate.is_absolute():
        resolved = candidate.resolve()
        if not any(root == resolved or root in resolved.parents for root in (storage_root, work_root)):
            raise ReconstructionError("Absolute capture path is outside allowed roots")
        return resolved
    return None


def _copy_private_object(url: str, target: Path) -> bool:
    if not url.startswith("private://"):
        return False
    storage_key = url.removeprefix("private://")
    try:
        data = read_private_bytes(storage_key)
    except Exception as exc:
        raise ReconstructionError("Unable to read private capture object") from exc
    if not data:
        raise ReconstructionError("Private capture object is empty")
    if len(data) > 500_000_000:
        raise ReconstructionError("Private capture object exceeds 500 MB")
    target.write_bytes(data)
    return True


def _download_capture(url: str, target: Path, settings: Settings) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ReconstructionError(f"Unsupported capture URL: {url}")
    try:
        with httpx.stream(
            "GET",
            url,
            timeout=settings.provider_http_timeout_seconds,
            follow_redirects=False,
        ) as response:
            response.raise_for_status()
            total = 0
            with target.open("wb") as output:
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > 500_000_000:
                        raise ReconstructionError("Downloaded capture exceeds 500 MB")
                    output.write(chunk)
    except httpx.HTTPError as exc:
        raise ReconstructionError(f"Unable to download capture: {url}") from exc


def _materialize_inputs(
    inputs: list[ReconstructionInput],
    *,
    target_dir: Path,
    settings: Settings,
) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    materialized: list[Path] = []
    for index, item in enumerate(inputs, 1):
        suffix = (
            mimetypes.guess_extension(item.mime_type)
            or Path(urlparse(item.url).path).suffix
            or ".bin"
        )
        target = target_dir / f"capture-{index:04d}{suffix}"
        local_source = _local_storage_source(item.url, settings)
        if local_source:
            if not local_source.is_file():
                raise ReconstructionError(f"Capture file does not exist: {item.url}")
            if local_source.stat().st_size > 500_000_000:
                raise ReconstructionError("Capture file exceeds 500 MB")
            shutil.copyfile(local_source, target)
        elif not _copy_private_object(item.url, target):
            _download_capture(item.url, target, settings)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        expected = item.sha256.lower()
        if len(expected) >= 32 and digest != expected:
            raise ReconstructionError(f"Capture checksum mismatch: {item.url}")
        materialized.append(target)
    return materialized


class FixtureBackend:
    name = "fixture"

    def __init__(self, settings: Settings):
        if not settings.fixtures_allowed:
            raise ReconstructionError("Fixture reconstruction is disabled in production")
        self.settings = settings

    def run(
        self,
        *,
        job_id: str,
        inputs: list[ReconstructionInput],
        representation: str,
        progress: ProgressCallback,
    ) -> ReconstructionResult:
        work = _safe_work_dir(self.settings, job_id)
        progress("quality_check", 15, {"file_count": len(inputs), "backend": self.name})
        progress("camera_reconstruction", 40, {"fixture": True})
        progress("dense_reconstruction", 65, {"fixture": True})
        progress("optimization", 80, {"fixture": True})
        if representation == "gaussian_splat":
            output = work / f"{job_id}.ply"
            output.write_text(
                "ply\nformat ascii 1.0\nelement vertex 0\nend_header\n",
                encoding="utf-8",
            )
            asset_type = "gaussian_splat"
        else:
            output = work / f"{job_id}.glb"
            body = bytes(116)
            output.write_bytes(b"glTF" + (2).to_bytes(4, "little") + (128).to_bytes(4, "little") + body)
            asset_type = "glb"
        progress("preview", 92, {"fixture": True})
        return ReconstructionResult(
            output,
            asset_type,
            {"pipeline": "fixture", "input_count": len(inputs)},
        )


class COLMAPBackend:
    name = "colmap"

    def __init__(self, settings: Settings):
        self.settings = settings

    def run(
        self,
        *,
        job_id: str,
        inputs: list[ReconstructionInput],
        representation: str,
        progress: ProgressCallback,
    ) -> ReconstructionResult:
        if representation == "gaussian_splat":
            raise ReconstructionError("COLMAP backend does not export gaussian splats; use Nerfstudio")
        work = _safe_work_dir(self.settings, job_id)
        images = work / "images"
        _materialize_inputs(inputs, target_dir=images, settings=self.settings)
        database = work / "database.db"
        sparse = work / "sparse"
        dense = work / "dense"
        sparse.mkdir()
        dense.mkdir()
        log = work / "pipeline.log"
        binary = self.settings.colmap_binary
        timeout = self.settings.reconstruction_command_timeout_seconds

        progress("quality_check", 10, {"file_count": len(inputs), "backend": self.name})
        _run(
            [
                binary,
                "feature_extractor",
                "--database_path",
                str(database),
                "--image_path",
                str(images),
                "--ImageReader.single_camera",
                "1",
            ],
            timeout=timeout,
            cwd=work,
            log_path=log,
        )
        progress("feature_extraction", 25, {})
        _run(
            [binary, "exhaustive_matcher", "--database_path", str(database)],
            timeout=timeout,
            cwd=work,
            log_path=log,
        )
        progress("feature_matching", 38, {})
        _run(
            [
                binary,
                "mapper",
                "--database_path",
                str(database),
                "--image_path",
                str(images),
                "--output_path",
                str(sparse),
            ],
            timeout=timeout,
            cwd=work,
            log_path=log,
        )
        models = sorted(path for path in sparse.iterdir() if path.is_dir())
        if not models:
            raise ReconstructionError("COLMAP did not produce a sparse model")
        model = models[0]
        progress("camera_reconstruction", 52, {"model": str(model)})
        _run(
            [
                binary,
                "image_undistorter",
                "--image_path",
                str(images),
                "--input_path",
                str(model),
                "--output_path",
                str(dense),
                "--output_type",
                "COLMAP",
            ],
            timeout=timeout,
            cwd=work,
            log_path=log,
        )
        _run(
            [
                binary,
                "patch_match_stereo",
                "--workspace_path",
                str(dense),
                "--workspace_format",
                "COLMAP",
                "--PatchMatchStereo.geom_consistency",
                "true",
            ],
            timeout=timeout,
            cwd=work,
            log_path=log,
        )
        progress("dense_reconstruction", 75, {})
        fused = work / f"{job_id}.ply"
        _run(
            [
                binary,
                "stereo_fusion",
                "--workspace_path",
                str(dense),
                "--workspace_format",
                "COLMAP",
                "--input_type",
                "geometric",
                "--output_path",
                str(fused),
            ],
            timeout=timeout,
            cwd=work,
            log_path=log,
        )
        if not fused.exists() or fused.stat().st_size == 0:
            raise ReconstructionError("COLMAP stereo fusion produced no output")
        progress("preview", 92, {"points_path": str(fused)})
        return ReconstructionResult(
            fused,
            "point_cloud",
            {"pipeline": "colmap", "input_count": len(inputs), "log_path": str(log)},
        )


class NerfstudioBackend:
    name = "nerfstudio"

    def __init__(self, settings: Settings):
        self.settings = settings

    def run(
        self,
        *,
        job_id: str,
        inputs: list[ReconstructionInput],
        representation: str,
        progress: ProgressCallback,
    ) -> ReconstructionResult:
        work = _safe_work_dir(self.settings, job_id)
        images = work / "images"
        processed = work / "processed"
        runs = work / "runs"
        exported = work / "exported"
        _materialize_inputs(inputs, target_dir=images, settings=self.settings)
        log = work / "pipeline.log"
        timeout = self.settings.reconstruction_command_timeout_seconds

        progress("quality_check", 10, {"file_count": len(inputs), "backend": self.name})
        _run(
            [
                self.settings.nerfstudio_process_binary,
                "images",
                "--data",
                str(images),
                "--output-dir",
                str(processed),
                "--matching-method",
                "exhaustive",
            ],
            timeout=timeout,
            cwd=work,
            log_path=log,
        )
        progress("camera_reconstruction", 35, {})
        method = "splatfacto" if representation == "gaussian_splat" else "nerfacto"
        _run(
            [
                self.settings.nerfstudio_train_binary,
                method,
                "--data",
                str(processed),
                "--output-dir",
                str(runs),
                "--viewer.quit-on-train-completion",
                "True",
            ],
            timeout=timeout,
            cwd=work,
            log_path=log,
        )
        configs = sorted(
            runs.rglob("config.yml"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not configs:
            raise ReconstructionError("Nerfstudio did not produce a training config")
        config = configs[0]
        progress("training", 70, {"method": method, "config": str(config)})
        exported.mkdir(parents=True, exist_ok=True)
        if representation == "gaussian_splat":
            command = [
                self.settings.nerfstudio_export_binary,
                "gaussian-splat",
                "--load-config",
                str(config),
                "--output-dir",
                str(exported),
            ]
            asset_type = "gaussian_splat"
        else:
            command = [
                self.settings.nerfstudio_export_binary,
                "poisson",
                "--load-config",
                str(config),
                "--output-dir",
                str(exported),
            ]
            asset_type = "mesh"
        _run(command, timeout=timeout, cwd=work, log_path=log)
        progress("optimization", 85, {})
        candidates = sorted(
            [*exported.rglob("*.ply"), *exported.rglob("*.splat"), *exported.rglob("*.glb")],
            key=lambda path: path.stat().st_size,
            reverse=True,
        )
        if not candidates:
            raise ReconstructionError("Nerfstudio export produced no supported artifact")
        output = candidates[0]
        auxiliary: dict[str, Path] = {}
        if representation != "gaussian_splat" and self.settings.gltf_converter_binary:
            glb = work / f"{job_id}.glb"
            _run(
                [self.settings.gltf_converter_binary, str(output), str(glb)],
                timeout=timeout,
                cwd=work,
                log_path=log,
            )
            if glb.exists() and glb.stat().st_size:
                output = glb
                asset_type = "glb"
        if output.suffix.lower() == ".glb" and self.settings.usdz_converter_binary:
            usdz = work / f"{job_id}.usdz"
            _run(
                [self.settings.usdz_converter_binary, str(output), str(usdz)],
                timeout=timeout,
                cwd=work,
                log_path=log,
            )
            if usdz.exists() and usdz.stat().st_size:
                auxiliary["usdz"] = usdz
        progress("preview", 94, {"output": str(output)})
        return ReconstructionResult(
            output,
            asset_type,
            {
                "pipeline": "nerfstudio",
                "method": method,
                "input_count": len(inputs),
                "config": str(config),
                "log_path": str(log),
            },
            auxiliary,
        )


def get_reconstruction_backend(
    name: str | None = None,
    settings: Settings | None = None,
) -> ReconstructionBackend:
    settings = settings or get_settings()
    normalized = (name or settings.reconstruction_backend).strip().lower()
    if normalized == "fixture":
        return FixtureBackend(settings)
    if normalized == "colmap":
        return COLMAPBackend(settings)
    if normalized == "nerfstudio":
        return NerfstudioBackend(settings)
    raise ReconstructionError(f"Unsupported reconstruction backend: {normalized}")
