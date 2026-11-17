from fastapi import FastAPI

app = FastAPI(title="Elective Capstone")


@app.get("/health")
def health():
    return {"status": "ok"}