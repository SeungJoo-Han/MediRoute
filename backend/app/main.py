import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from .routers import navigation, shuttle

app = FastAPI(
    title="MediRoute API",
    description="대학병원 셔틀버스 포함 최적 경로 안내 서비스",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(navigation.router, prefix="/api")
app.include_router(shuttle.router, prefix="/api")

# 프론트엔드 정적 파일 서빙
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "../../frontend")
FRONTEND_DIR = os.path.abspath(FRONTEND_DIR)

if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_index():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
