from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import engine, Base
from .routers import auth, admin, classes, tests, payments, students

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Wandor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth)       # was auth.router — now auth IS the router
app.include_router(admin)
app.include_router(classes)
app.include_router(tests)
app.include_router(payments)
app.include_router(students)


@app.get("/health")
def health():
    return {"status": "alive"}