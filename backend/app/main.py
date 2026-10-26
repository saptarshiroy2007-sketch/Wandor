import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DataError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .database import engine, Base, settings
from .routers import auth, classes, tests, payments, students, attendance, uploads, parents, institute, batches, billing, admin
from .services.fee_reminders import start_scheduler, stop_scheduler

# NOTE: alembic/ is the source of truth for schema changes - migrations, not this
# call, are what should evolve the schema from here on. create_all() only creates
# tables that don't exist yet; it never alters existing ones, so it can't cause data
# loss - but it CAN cause the exact drift bug we hit running `alembic upgrade head`
# against the real Supabase DB (teacher_batch_assignments already existed via
# create_all(), so alembic's own CREATE TABLE for it 500'd with DuplicateTable, even
# though alembic_version still said we were behind). Every future migration that adds
# a whole new table (like otp_codes did) would hit the same thing again on Postgres,
# for as long as this line ran unconditionally.
#
# Restricting this to sqlite means it still "just works" for a disposable local
# SQLite dev db (no migrations needed to get started), while Postgres - Supabase,
# Render, anything real - is only ever touched by alembic.
if settings.database_url.startswith("sqlite"):
    Base.metadata.create_all(bind=engine)

app = FastAPI(title="Wandor API")

@app.exception_handler(DataError)
async def _bad_value_in_url(request: Request, exc: DataError):
    """Postgres raises DataError when a path id isn't a valid UUID ('/students/nope'), which
    surfaced as a 500; SQLite just found nothing and returned 404. An id that can't exist is a 404
    on both."""
    return JSONResponse(status_code=404, content={"detail": "Not found"})


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this before you actually ship
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Account-Status", "X-Account-Can-Pay"],
)

app.include_router(auth.router)
app.include_router(classes.router)
app.include_router(tests.router)
app.include_router(payments.router)
app.include_router(billing.router)
app.include_router(students.router)
app.include_router(attendance.router)
app.include_router(uploads.router)
app.include_router(parents.router)
app.include_router(institute.router)
app.include_router(batches.router)
app.include_router(admin.router)

# Only relevant when storage_backend == "local" - serves uploaded test documents back out.
# Once you're on multiple backend instances behind a load balancer, switch to storage_backend=s3
# instead (see services/storage.py), since local disk won't be shared across instances.
if settings.storage_backend == "local":
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")


@app.on_event("startup")
def _on_startup():
    if settings.razorpay_key_id and settings.fee_platform_commission_bps <= 0:
        # Razorpay's fee on every student fee payment is charged to the PLATFORM account.
        # With no commission the institute gets 100% and each online payment costs you money.
        logging.getLogger(__name__).warning(
            "FEE_PLATFORM_COMMISSION_BPS is 0: Razorpay's fee on every online student fee "
            "payment is absorbed by the platform. Set a commission before enabling online fees."
        )
    start_scheduler()


@app.on_event("shutdown")
def _on_shutdown():
    stop_scheduler()


@app.get("/health")
def health():
    return {"status": "alive"}
