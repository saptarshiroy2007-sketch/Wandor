from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .database import engine, Base
from .routers import auth, admin, classes, tests, payments, students

uploads_dir = Path(__file__).resolve().parent.parent / 'uploads'
uploads_dir.mkdir(parents=True, exist_ok=True)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Wandor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this before you actually ship
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(classes.router)
app.include_router(tests.router)
app.include_router(payments.router)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")


@app.get("/health")
def health():
    return {"status": "alive"}
