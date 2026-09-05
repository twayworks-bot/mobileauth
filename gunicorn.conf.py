# Gunicorn configuration file for running ASGI applications using Uvicorn workers
import multiprocessing

# Gunicorn runs our FastAPI ASGI application using the Uvicorn worker class.
worker_class = "uvicorn.workers.UvicornWorker"

# You can also add other configurations here if needed, but since we specify bindings, workers, log levels,
# access/error logfiles, and capture output directly in the CMD command, those arguments will take precedence.
