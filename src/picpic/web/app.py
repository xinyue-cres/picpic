from __future__ import annotations

import pathlib
import webbrowser
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..db import open_db
from ..rules import DEFAULT_BLUR_THRESHOLD, apply_rules
from ..thumbs import ensure_thumb
from ..trash import purge_trash, restore_photos, trash_photos


_STATIC_DIR = pathlib.Path(__file__).parent / "static"


def _within_library(p: pathlib.Path, library: pathlib.Path) -> bool:
    """Return True if resolved p is inside the resolved library root."""
    return p.resolve().is_relative_to(library.resolve())


def _photo_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "path": row["path"],
        "verdict": row["verdict"],
        "verdict_reason": row["verdict_reason"],
        "dup_group": row["dup_group"],
        "blur_score": row["blur_score"],
        "is_screenshot": row["is_screenshot"],
        "width": row["width"],
        "height": row["height"],
    }


def create_app(library: pathlib.Path) -> FastAPI:
    library = library.resolve()
    db_path = library / "picpic.db"

    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^http://(127\.0\.0\.1|localhost)(:\d+)?$",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if _STATIC_DIR.exists():
        app.mount(
            "/static", StaticFiles(directory=str(_STATIC_DIR)), name="static"
        )

    @app.get("/")
    def index():
        idx = _STATIC_DIR / "index.html"
        if not idx.exists():
            return JSONResponse({"error": "ui missing"}, status_code=500)
        return FileResponse(str(idx))

    @app.get("/api/photos")
    def list_photos(
        tab: str = Query("candidates"),
        min_blur: float | None = Query(None),
    ):
        conn = open_db(db_path)
        try:
            if tab == "candidates":
                sql = (
                    "SELECT * FROM photos "
                    "WHERE status='active' AND verdict='trash_candidate'"
                )
                params: list[Any] = []
                if min_blur is not None:
                    sql += (
                        " AND (verdict_reason<>'blurry' OR blur_score<?)"
                    )
                    params.append(min_blur)
                sql += " ORDER BY id"
                rows = conn.execute(sql, params).fetchall()
            elif tab == "similar":
                rows = conn.execute(
                    "SELECT * FROM photos "
                    "WHERE status='active' AND dup_group IS NOT NULL "
                    "ORDER BY dup_group, id"
                ).fetchall()
            elif tab == "trashed":
                rows = conn.execute(
                    "SELECT * FROM photos WHERE status='trashed' "
                    "ORDER BY trashed_at DESC, id"
                ).fetchall()
            else:
                raise HTTPException(400, f"unknown tab: {tab}")
            return {"photos": [_photo_dict(r) for r in rows]}
        finally:
            conn.close()

    @app.post("/api/trash")
    def api_trash(payload: dict = Body(...)):
        ids = list(payload.get("ids") or [])
        conn = open_db(db_path)
        try:
            n = trash_photos(conn, library, ids)
        finally:
            conn.close()
        return {"moved": n}

    @app.post("/api/restore")
    def api_restore(payload: dict = Body(...)):
        ids = list(payload.get("ids") or [])
        conn = open_db(db_path)
        try:
            n = restore_photos(conn, library, ids)
        finally:
            conn.close()
        return {"restored": n}

    @app.post("/api/purge")
    def api_purge(payload: dict = Body(default={})):
        conn = open_db(db_path)
        try:
            n = purge_trash(conn, library)
        finally:
            conn.close()
        return {"deleted": n}

    @app.post("/api/rules")
    def api_rules(payload: dict = Body(default={})):
        threshold = float(
            payload.get("blur_threshold", DEFAULT_BLUR_THRESHOLD)
        )
        conn = open_db(db_path)
        try:
            report = apply_rules(conn, blur_threshold=threshold)
        finally:
            conn.close()
        return {
            "kept": report.kept,
            "candidates": report.candidates,
            "by_reason": report.by_reason,
        }

    def _photo_row(photo_id: int):
        conn = open_db(db_path)
        try:
            row = conn.execute(
                "SELECT id, path, status FROM photos WHERE id=?",
                (photo_id,),
            ).fetchone()
        finally:
            conn.close()
        return row

    @app.get("/thumb/{photo_id}")
    def get_thumb(photo_id: int):
        row = _photo_row(photo_id)
        if row is None:
            raise HTTPException(404, "no such photo")
        source = pathlib.Path(row["path"])
        if row["status"] == "trashed":
            # look inside trash for the moved file
            from ..trash import TRASH_DIRNAME
            trash = library / TRASH_DIRNAME
            for entry in trash.iterdir() if trash.exists() else []:
                if entry.name.startswith(f"{photo_id}__"):
                    source = entry
                    break
        if not _within_library(source, library):
            raise HTTPException(403, "path outside library")
        if not source.exists():
            raise HTTPException(404, "source missing")
        thumb = ensure_thumb(library, photo_id, source)
        return FileResponse(str(thumb), media_type="image/jpeg")

    @app.get("/photo/{photo_id}")
    def get_photo(photo_id: int):
        row = _photo_row(photo_id)
        if row is None:
            raise HTTPException(404, "no such photo")
        source = pathlib.Path(row["path"])
        if not _within_library(source, library):
            raise HTTPException(403, "path outside library")
        if not source.exists():
            raise HTTPException(404, "no such photo")
        return FileResponse(str(source))

    return app


def serve(
    library: pathlib.Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    import uvicorn
    app = create_app(library)
    if open_browser:
        webbrowser.open(f"http://{host}:{port}/")
    uvicorn.run(app, host=host, port=port, log_level="info")
