import os
import threading
import webbrowser

from flask import Flask

from config import BASE_DIR, UPLOAD_FOLDER, MPL_CACHE_DIR
from db import init_auth_db

from routes.main import main_bp
from routes.plate_overview import plate_overview_bp
from routes.chromatic import chromatic_bp
from routes.runs import runs_bp

os.environ["MPLCONFIGDIR"] = MPL_CACHE_DIR

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

app.register_blueprint(main_bp)
app.register_blueprint(plate_overview_bp)
app.register_blueprint(chromatic_bp)
app.register_blueprint(runs_bp)

init_auth_db()


if __name__ == "__main__":
    host = "127.0.0.1"
    port = 5051
    url = f"http://localhost:{port}/"

    threading.Timer(1.0, lambda: webbrowser.open_new_tab(url)).start()

    app.run(host=host, port=port, debug=False, use_reloader=False)
