from fastapi.responses import JSONResponse
from fastapi import APIRouter
import yt_dlp

router = APIRouter(prefix="/song")


ydl_opts = {
    "format": "bestaudio/best",
    "merge_output_format": "mp3",
    "outtmpl": "./songs/%(title)s.%(ext)s",
}
ydl = yt_dlp.YoutubeDL(ydl_opts)


@router.get("/download")
def download(url: str):
    ydl.download([url])

    response = JSONResponse({"status": "Funzia", "url": url})
    return response
