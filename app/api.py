from fastapi import FastAPI, APIRouter, Request, Response
from fastapi.responses import JSONResponse


router = APIRouter()


@router.get('/')
async def index(request: Request, response: Response) -> Response:
    return JSONResponse({"hello": "world"})

api = FastAPI()
api.include_router(router)
