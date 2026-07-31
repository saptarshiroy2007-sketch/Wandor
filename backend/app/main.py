from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .database import engine, Base, settings
from .routers import auth, classes, tests, payments, students, attendance, uploads, parents, institute
from .services.fee_reminders import start_scheduler, stop_scheduler

# NOTE: now that alembic/ exists, migrations are the source of truth for schema changes.
# create_all() here is just a convenience for fast local dev bootstrap on a throwaway DB -
# run `alembic upgrade head` instead for anything staging/production.
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Wandor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this before you actually ship
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(classes.router)
app.include_router(tests.router)
app.include_router(payments.router)
app.include_router(students.router)
app.include_router(attendance.router)
app.include_router(uploads.router)
app.include_router(parents.router)
app.include_router(institute.router)

# Only relevant when storage_backend == "local" - serves uploaded test documents back out.
# Once you're on multiple backend instances behind a load balancer, switch to storage_backend=s3
# instead (see services/storage.py), since local disk won't be shared across instances.
if settings.storage_backend == "local":
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")


@app.on_event("startup")
def _on_startup():
    start_scheduler()


@app.on_event("shutdown")
def _on_shutdown():
    stop_scheduler()


@app.get("/health")
def health():
    return {"status": "alive"}
