# Copyright 2016-2020 Christoph Reiter
# SPDX-License-Identifier: MIT

import os

from flask import Flask
from jinja2 import StrictUndefined

from .web import packages
from .fetch import start_update_thread


app = Flask(__name__)
app.register_blueprint(packages)
app.jinja_env.undefined = StrictUndefined

if not os.environ.get("NO_UPDATE_THREAD"):
    start_update_thread()
