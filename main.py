from fastapi import FastAPI

app = FastAPI(title="Virtual Coach Backend")

@app.get("/")
async def read_root():
    return {"message": "Welcome to the Virtual Coach API"}

# Add other endpoints here later (assessment, plans, admin, etc.) 