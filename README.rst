MSYS2 Web Interface
===================

A simple web interface for browsing the MSYS2 repos.

Rebuild CSS/JS (optional)::

    cd frontend
    npm install
    npm run build

Run for Development::

    uv run run.py --cache

Run for Production::

    # See the Dockerfile
    docker build .
    docker run --rm -it -p 8080:80 <image-id>
