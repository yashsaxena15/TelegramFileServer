# src/Backend/routes/media_routes.py

import os
import sys
import json
import asyncio
import urllib.parse
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Request, HTTPException, Response, Query
from fastapi.responses import StreamingResponse, JSONResponse

from ..security.credentials import require_auth
from src.Database import database
from d4rk.Logs import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/media", tags=["Media Processing"])

# In-memory cache for probed media metadata (file_name -> metadata dict)
_MEDIA_INFO_CACHE: Dict[str, Any] = {}

LANGUAGE_MAP = {
    "hin": "Hindi",
    "eng": "English",
    "tam": "Tamil",
    "tel": "Telugu",
    "mal": "Malayalam",
    "kan": "Kannada",
    "ben": "Bengali",
    "mar": "Marathi",
    "pan": "Punjabi",
    "guj": "Gujarati",
    "spa": "Spanish",
    "fre": "French",
    "fra": "French",
    "ger": "German",
    "deu": "German",
    "ita": "Italian",
    "rus": "Russian",
    "jpn": "Japanese",
    "kor": "Korean",
    "chi": "Chinese",
    "zho": "Chinese",
    "ara": "Arabic",
    "por": "Portuguese",
    "und": "Default Audio",
}

# Standard resolution map (height in pixels)
RESOLUTION_HEIGHT_MAP = {
    "144p": 144,
    "240p": 240,
    "360p": 360,
    "480p": 480,
    "720p": 720,
    "1080p": 1080,
    "1440p": 1440,
    "2k": 1440,
    "2160p": 2160,
    "4k": 2160,
}


from src.Config import PORT


def _get_internal_stream_url(file_name: str, token: Optional[str] = None) -> str:
    """Generate internal loopback URL for ffmpeg/ffprobe to stream from local Uvicorn"""
    encoded_name = urllib.parse.quote(file_name)
    port = PORT or 8000
    url = f"http://127.0.0.1:{port}/dl/{encoded_name}?inline=1"
    if token:
        url += f"&token={urllib.parse.quote(token)}"
    return url


@router.get("/info/{file_name:path}")
async def get_media_info(request: Request, file_name: str, token: Optional[str] = None):
    """
    Probe media file using ffprobe to detect resolution, audio tracks, and subtitle tracks.
    Results are cached in memory and database for instant responses.
    """
    try:
        user = require_auth(request)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Authentication required")

    decoded_file_name = urllib.parse.unquote(file_name)

    # Check memory cache
    if decoded_file_name in _MEDIA_INFO_CACHE:
        return _MEDIA_INFO_CACHE[decoded_file_name]

    # Find file in database
    file_data = database.Files.find_one({"file_name": decoded_file_name})
    if not file_data:
        base_name = os.path.basename(decoded_file_name)
        file_data = database.Files.find_one({"file_name": base_name})

    if not file_data:
        raise HTTPException(status_code=404, detail="File not found")

    actual_file_name = file_data.get("file_name", decoded_file_name)

    # Check if media_info is already stored in database
    if file_data.get("media_info"):
        db_info = file_data["media_info"]
        _MEDIA_INFO_CACHE[decoded_file_name] = db_info
        return db_info

    # Extract auth token from request
    auth_token = token or request.query_params.get("token")
    if not auth_token:
        token_doc = database.Users.db["AuthTokens"].find_one({"username": "admin"})
        if token_doc:
            auth_token = token_doc.get("auth_token")

    stream_url = _get_internal_stream_url(actual_file_name, auth_token)

    cmd = [
        "ffprobe",
        "-v", "error",
        "-analyzeduration", "2000000",
        "-probesize", "2000000",
        "-show_entries", "stream=index,codec_type,codec_name,width,height:stream_tags=language,title",
        "-show_entries", "format=duration,size",
        "-of", "json",
        stream_url
    ]

    logger.info(f"[MediaRoutes] Probing media file: {actual_file_name}")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=25.0)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        logger.warning(f"[MediaRoutes] ffprobe timed out for {actual_file_name}")
        # Return fallback with default audio track
        fallback = {
            "file_name": actual_file_name,
            "width": None,
            "height": None,
            "video_codec": None,
            "duration": 0,
            "audio_tracks": [{"index": 0, "stream_index": 1, "codec": "aac", "language": "Default", "title": "Default Audio"}],
            "subtitle_tracks": []
        }
        return fallback
    except Exception as e:
        logger.warning(f"[MediaRoutes] ffprobe error: {e}, using default fallback metadata")
        return {
            "file_name": actual_file_name,
            "width": None,
            "height": None,
            "video_codec": None,
            "duration": 0,
            "audio_tracks": [{"index": 0, "stream_index": 1, "codec": "aac", "language": "Default", "title": "Default Audio"}],
            "subtitle_tracks": []
        }

    if proc.returncode != 0:
        logger.warning(f"[MediaRoutes] ffprobe exited with code {proc.returncode}: {stderr.decode('utf-8', errors='ignore')}")
        fallback = {
            "file_name": actual_file_name,
            "width": None,
            "height": None,
            "video_codec": None,
            "duration": 0,
            "audio_tracks": [{"index": 0, "stream_index": 1, "codec": "aac", "language": "Default", "title": "Default Audio"}],
            "subtitle_tracks": []
        }
        return fallback

    try:
        probe_data = json.loads(stdout.decode("utf-8"))
    except Exception as e:
        logger.error(f"[MediaRoutes] Failed to parse ffprobe json: {e}")
        fallback = {
            "file_name": actual_file_name,
            "width": None,
            "height": None,
            "video_codec": None,
            "duration": 0,
            "audio_tracks": [{"index": 0, "stream_index": 1, "codec": "aac", "language": "Default", "title": "Default Audio"}],
            "subtitle_tracks": []
        }
        return fallback

    streams = probe_data.get("streams", [])
    format_info = probe_data.get("format", {})

    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    subtitle_streams = [s for s in streams if s.get("codec_type") == "subtitle"]

    main_video = video_streams[0] if video_streams else {}
    width = main_video.get("width")
    height = main_video.get("height")
    video_codec = main_video.get("codec_name")

    audio_tracks = []
    for i, s in enumerate(audio_streams):
        tags = s.get("tags") or {}
        raw_lang = (tags.get("language") or "").lower()
        readable_lang = LANGUAGE_MAP.get(raw_lang, tags.get("language") or f"Audio {i + 1}")
        custom_title = tags.get("title")
        display_title = custom_title or readable_lang or f"Track {i + 1}"
        audio_tracks.append({
            "index": i,
            "stream_index": s.get("index"),
            "codec": s.get("codec_name"),
            "language": readable_lang,
            "title": display_title,
        })

    # Ensure at least 1 audio track is present
    if not audio_tracks:
        audio_tracks = [{
            "index": 0,
            "stream_index": 1,
            "codec": "aac",
            "language": "Default",
            "title": "Default Audio"
        }]

    subtitle_tracks = []
    for i, s in enumerate(subtitle_streams):
        tags = s.get("tags") or {}
        raw_lang = (tags.get("language") or "").lower()
        readable_lang = LANGUAGE_MAP.get(raw_lang, tags.get("language") or f"Subtitle {i + 1}")
        custom_title = tags.get("title")
        display_title = custom_title or readable_lang or f"Subtitle {i + 1}"
        subtitle_tracks.append({
            "index": i,
            "stream_index": s.get("index"),
            "codec": s.get("codec_name"),
            "language": readable_lang,
            "title": display_title,
        })

    result = {
        "file_name": actual_file_name,
        "width": width,
        "height": height,
        "video_codec": video_codec,
        "duration": float(format_info.get("duration", 0) or 0),
        "audio_tracks": audio_tracks,
        "subtitle_tracks": subtitle_tracks,
    }

    # Cache in memory and MongoDB
    _MEDIA_INFO_CACHE[decoded_file_name] = result
    if file_data and "_id" in file_data:
        try:
            database.Files.update_one(
                {"_id": file_data["_id"]},
                {"$set": {"media_info": result}}
            )
        except Exception as e:
            logger.warning(f"[MediaRoutes] Could not save media_info to DB: {e}")

    return result


@router.get("/subtitles/{file_name:path}")
async def get_subtitles(
    request: Request,
    file_name: str,
    track: int = Query(0, description="0-indexed subtitle track"),
    token: Optional[str] = None
):
    """
    Extract embedded subtitle track from video container into WebVTT text format on-the-fly.
    """
    try:
        user = require_auth(request)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Authentication required")

    decoded_file_name = urllib.parse.unquote(file_name)

    auth_token = token or request.query_params.get("token")
    if not auth_token:
        token_doc = database.Users.db["AuthTokens"].find_one({"username": "admin"})
        if token_doc:
            auth_token = token_doc.get("auth_token")

    stream_url = _get_internal_stream_url(decoded_file_name, auth_token)

    cmd = [
        "ffmpeg",
        "-v", "error",
        "-i", stream_url,
        "-map", f"0:s:{track}",
        "-f", "webvtt",
        "-"
    ]

    logger.info(f"[MediaRoutes] Extracting subtitle track {track} for {decoded_file_name}")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        raise HTTPException(status_code=504, detail="Subtitle extraction timed out")
    except Exception as e:
        logger.error(f"[MediaRoutes] Subtitle extraction error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    if proc.returncode != 0:
        err_msg = stderr.decode("utf-8", errors="ignore")
        logger.warning(f"[MediaRoutes] ffmpeg subtitle error: {err_msg}")
        # Return minimal valid empty WebVTT if track not found
        return Response(
            content="WEBVTT\n\n",
            media_type="text/vtt; charset=utf-8",
            headers={"Access-Control-Allow-Origin": "*"}
        )

    return Response(
        content=stdout,
        media_type="text/vtt; charset=utf-8",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=86400",
        }
    )


@router.get("/stream/{file_name:path}")
async def media_transcode_stream(
    request: Request,
    file_name: str,
    quality: Optional[str] = Query(None, description="Quality preset (e.g. 480p, 360p, 240p, 144p, original)"),
    audio_track: Optional[int] = Query(None, description="0-indexed audio track to select"),
    start_time: Optional[float] = Query(0.0, description="Start timestamp in seconds for seeking"),
    token: Optional[str] = Query(None, description="Auth token"),
):
    """
    Stream video with quality downscaling or custom audio track selection on-the-fly.
    - If quality is original and audio_track is 0 or None: forwards/redirects directly to raw stream (0% CPU).
    - If audio_track > 0 and quality is original: fast stream remuxing with -c:v copy (0% video CPU).
    - If quality is lower (e.g. 480p, 360p): encodes video downscale using single-core ultrafast preset.
    """
    try:
        user = require_auth(request)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Authentication required")

    decoded_file_name = urllib.parse.unquote(file_name)

    auth_token = token or request.query_params.get("token")
    if not auth_token:
        token_doc = database.Users.db["AuthTokens"].find_one({"username": "admin"})
        if token_doc:
            auth_token = token_doc.get("auth_token")

    stream_url = _get_internal_stream_url(decoded_file_name, auth_token)

    is_original_quality = (
        not quality
        or quality.lower() in ("original", "auto", "source")
    )
    is_default_audio = (audio_track is None or audio_track == 0)

    ext = decoded_file_name.rsplit(".", 1)[-1].lower() if "." in decoded_file_name else ""
    is_browser_native_container = ext in ("mp4", "m4v", "webm", "mp3", "ogg", "wav", "m4a")

    # Only redirect to raw stream if container is natively playable in browser, seeking is at 0, original quality, and default audio
    if is_browser_native_container and is_original_quality and is_default_audio and (not start_time or start_time <= 0):
        # Redirect directly to raw stream handler to avoid any ffmpeg process
        return Response(status_code=307, headers={"Location": f"/dl/{urllib.parse.quote(decoded_file_name)}?inline=1&token={auth_token or ''}"})

    # Prepare FFmpeg command with fast seeking and zero-latency probing
    cmd = [
        "ffmpeg", "-v", "error",
        "-fflags", "+nobuffer+fastseek",
        "-analyzeduration", "2000000",
        "-probesize", "2000000",
    ]

    if start_time and start_time > 0:
        # Fast seeking before input
        cmd.extend(["-ss", f"{start_time:.3f}"])

    cmd.extend(["-i", stream_url])

    # Audio mapping
    selected_audio = audio_track if audio_track is not None else 0
    cmd.extend(["-map", "0:v:0", "-map", f"0:a:{selected_audio}?"])

    target_height = RESOLUTION_HEIGHT_MAP.get(quality.lower()) if quality else None

    if is_original_quality or not target_height:
        # Remux video without re-encoding (0% video CPU load!)
        cmd.extend(["-c:v", "copy", "-tag:v", "hvc1"])
    else:
        # Downscale video with single-thread ultrafast to protect VPS CPU
        scale_filter = f"scale=-2:{target_height}"
        cmd.extend([
            "-vf", scale_filter,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "28",
            "-threads", "1",
        ])

    # Ensure audio is browser-compatible stereo AAC (transcodes AC3/EAC3/DTS at < 2% CPU)
    cmd.extend([
        "-c:a", "aac",
        "-b:a", "192k",
        "-ac", "2",
        "-avoid_negative_ts", "make_zero",
        "-max_muxing_queue_size", "1024",
        "-f", "mp4",
        "-movflags", "frag_keyframe+empty_moov+default_base_moof",
        "pipe:1"
    ])

    logger.info(f"[MediaRoutes] Starting stream process: {' '.join(cmd)}")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
    except Exception as e:
        logger.error(f"[MediaRoutes] Failed to launch ffmpeg: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    async def stream_generator():
        chunk_size = 64 * 1024
        try:
            while True:
                chunk = await proc.stdout.read(chunk_size)
                if not chunk:
                    break
                yield chunk
        except (asyncio.CancelledError, GeneratorExit):
            logger.info("[MediaRoutes] Client disconnected, killing ffmpeg process")
        finally:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass

    return StreamingResponse(
        stream_generator(),
        media_type="video/mp4",
        headers={
            "Content-Type": "video/mp4",
            "Accept-Ranges": "none",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Access-Control-Allow-Origin": "*",
            "X-Content-Type-Options": "nosniff",
        }
    )
