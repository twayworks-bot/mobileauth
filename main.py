from fastapi import FastAPI
from fastapi.responses import RedirectResponse
import routes

# Initialize FastAPI App
app = FastAPI(
    title="holyseeds Auth System",
    description="Common Authentication System utilizing Keycloak Proxy Mode",
    version="1.0.0"
)

# Register Web UI Auth Router
app.include_router(routes.router)

# Healthcheck endpoint for Docker container
@app.get("/auth/api/status")
async def health_check():
    return {"status": "ok", "service": "auth"}

# Redirect root endpoint to /auth/login for uniform entry point
@app.get("/")
async def root():
    return RedirectResponse(url="/auth/login")

if __name__ == "__main__":
    import uvicorn
    # Start ASGI Server on port 8000
    print("Starting holyseeds authentication service on http://localhost:8000...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
