
# Local Process API Orchestrator

This project provides a simple, hackable REST API to start, stop, and manage multiple local processes (like dev servers or background scripts). It's designed for situations where you need to programmatically control a set of services from another application, such as an automated test suite or a custom developer tool.

It acts as a lightweight, API-driven `docker-compose` for processes running directly on your host, without the overhead and abstraction of containerization.

## Key Advantages

*   **Programmatic Control:** Exposes your shell scripts to a clean REST API, making them controllable from other applications (e.g., test runners, CI/CD pipelines, custom GUIs).
*   **Simplicity and No Bloat:** The entire orchestrator is 3 Python files. It's trivial to audit the full codebase, understand how it works, and modify it for your specific needs.
*   **Unified Monitoring:** When run in the foreground, it provides a single, interleaved log stream from all managed services, perfect for interactive debugging.
*   **Automatic Restarts:** Automatically restarts any managed service that crashes, keeping your development environment stable.

## Setup

1.  Clone the repository.
2.  Install the required Python packages:
    ```bash
    pip install -r requirements.txt
    ```

## Configuration

Create a `config.yaml` file in the project's root directory. This file defines the services you want to manage, organized into groups. The orchestrator automatically expands `~` in `working_dir` to your user's home directory.

**Example `config.yaml`:**

```yaml
service_groups:
  # A group for running the main API and its worker
  "backend":
    - name: "my-api-service"
      working_dir: "~/dev/my-project/api"
      script: "./run-dev.sh"
    - name: "my-worker"
      working_dir: "~/dev/my-project/worker"
      script: "poetry run python worker.py"

  # A separate group for a front-end service
  "frontend":
    - name: "vite-dev-server"
      working_dir: "~/dev/my-project/frontend"
      script: "npm run dev"
```

## Usage

1.  **Start the Orchestrator:**
    ```bash
    uvicorn main:app --host 0.0.0.0 --port 8000
    ```
    The console will show the orchestrator's logs and will stream the output of any services you start.

2.  **Control Services via API:**
    Use `curl` or any API client to interact with the orchestrator.

    *   **Get the status of all configured services:**
        ```bash
        curl http://localhost:8000/services
        ```

    *   **Start all services in the "backend" group:**
        ```bash
        curl -X POST http://localhost:8000/services/start/backend
        ```

    *   **Stop all services in the "backend" group:**
        ```bash
        curl -X POST http://localhost:8000/services/stop/backend
        ```