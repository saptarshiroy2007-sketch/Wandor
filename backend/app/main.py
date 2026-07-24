from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import engine, Base
from .routers import auth, classes, tests, payments

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


@app.get("/health")
def health():
    return {"status": "alive"}
