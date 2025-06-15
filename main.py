from fastapi import FastAPI, HTTPException, status
from typing import List

from models import ServiceStatus
from process_manager import process_manager, print_orchestrator

app = FastAPI(
    title="Interactive Service Orchestrator",
    description="An API to start, stop, and monitor services from a YAML config.",
    version="2.0.0"
)

@app.on_event("startup")
def on_startup():
    """Start the background process monitor when the server starts."""
    process_manager.start_monitoring()

@app.on_event("shutdown")
def on_shutdown():
    """Gracefully stop all child processes when the API server shuts down."""
    print_orchestrator("API Server shutting down.", level="info")
    process_manager.stop_all()
    process_manager.stop_monitoring()
    print_orchestrator("Shutdown complete.", level="info")

@app.get("/services", response_model=List[ServiceStatus], summary="Get Status of All Configured Services")
def get_all_services_status():
    """
    Returns the current status of all services defined in config.yaml.
    """
    return process_manager.get_all_statuses()

@app.post("/services/start/{group_id}", response_model=List[ServiceStatus], status_code=status.HTTP_200_OK, summary="Start a Service Group")
def start_service_group(group_id: str):
    """
    Starts all services associated with the given group_id from config.yaml.
    """
    statuses = process_manager.start_group(group_id)
    if not statuses or statuses[0].detail == "Group ID not found in config.":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service group '{group_id}' not found in config.yaml"
        )
    return statuses

@app.post("/services/stop/{group_id}", status_code=status.HTTP_200_OK, summary="Stop a Service Group")
def stop_service_group(group_id: str):
    """
    Stops all running services associated with the given group_id.
    """
    process_manager.stop_group(group_id)
    return {"message": f"Stop command issued for service group '{group_id}'."}