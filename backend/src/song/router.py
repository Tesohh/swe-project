from fastapi.responses import JSONResponse
from fastapi import APIRouter

router = APIRouter(prefix="/song")


@router.get("/download")
def download(url: str):
    response = JSONResponse({"status": "Funzia", "url": url})
    return response
