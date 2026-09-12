# src/Backend/routes/frontend_routes.py

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, FileResponse
import os

router = APIRouter()

API_PREFIXES = (
    "auth",
    "files",
    "folders",
    "system",
    "user",
    "users",
    "telegram",
    "dl",
    "watch",
    "api",
    "docs",
    "redoc",
    "openapi.json",
)

@router.api_route("/{full_path:path}", methods=["GET", "HEAD"])
async def serve_frontend(request: Request, full_path: str):
    # Don't serve frontend for API routes or docs
    first_segment = full_path.strip("/").split("/")[0] if full_path.strip("/") else ""
    if first_segment in API_PREFIXES:
        return Response(status_code=404)
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    frontend_dist = os.path.normpath(os.path.join(current_dir, "..", "..", "frontend", "dist"))
    
    # 1. If requesting a static file from dist (e.g. favicon.ico, placeholder.svg, robots.txt)
    if full_path:
        requested_file = os.path.normpath(os.path.join(frontend_dist, full_path))
        if requested_file.startswith(frontend_dist) and os.path.isfile(requested_file):
            return FileResponse(requested_file)
    
    # 2. Serve built production frontend index.html for SPA routing
    dist_index = os.path.join(frontend_dist, "index.html")
    if os.path.isfile(dist_index):
        return FileResponse(dist_index)
    
    # 3. Fallback to development index.html if dist does not exist
    dev_index = os.path.normpath(os.path.join(current_dir, "..", "..", "frontend", "index.html"))
    if os.path.isfile(dev_index):
        return FileResponse(dev_index)
    
    # 4. Fallback if frontend is missing
    return HTMLResponse(
        content="""
        <!DOCTYPE html>
        <html>
        <head><title>File Server</title></head>
        <body><div id="root">Frontend build not found. Please build the frontend.</div></body>
        </html>
        """,
        status_code=404
    )