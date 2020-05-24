MSYS2 Web Interface
===================

A simple web interface for browsing the MSYS2 repos.

.. image:: https://ci.appveyor.com/api/projects/status/530781jtycsjpy6s/branch/master?svg=true
    :target: https://ci.appveyor.com/project/lazka/msys2-web/branch/master

.. image:: https://travis-ci.org/msys2/msys2-web.svg?branch=master
    :target: https://travis-ci.org/msys2/msys2-web

Rebuild CSS/JS (optional)::

    cd frontend
    npm install
    npm run build

Run for Development::

    poetry shell
    poetry install
    python run.py --cache

Run for Production::

    # See the Dockerfile

Webhook Config Environment Variables::

    GITHUB_WEBHOOK_SECRET=
    APPVEYOR_ACCOUNT=
    APPVEYOR_PROJECT=
    APPVEYOR_TOKEN=
