import yt_dlp
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/song")


download_opts = {
    "format": "bestaudio/best",
    "merge_output_format": "mp3",
    "outtmpl": "./songs/%(title)s.%(ext)s",
}

search_opts = {
    "quiet": True,
    "no_warnings": True,
    "js_runtimes": {"node": {"path": "/usr/bin/node"}},
}


@router.get("/download")
def download(url: str):
    with yt_dlp.YoutubeDL(download_opts) as ydl:
        ydl.download([url])

    response = JSONResponse({"status": "Funzia", "url": url})
    return response


@router.get("/search")
def search(query: str):
    with yt_dlp.YoutubeDL(search_opts) as ydl:
        info = ydl.extract_info(f"ytsearch{5}:{query}", download=False)

    results = []
    if info and "entries" in info:
        for entry in info["entries"]:
            results.append(
                {
                    "title": entry.get("title"),
                    "url": entry.get("webpage_url"),
                    "thumbnail": entry.get("thumbnail"),
                    "duration": entry.get("duration"),
                }
            )

    return JSONResponse({"status": "ok", "results": results})
