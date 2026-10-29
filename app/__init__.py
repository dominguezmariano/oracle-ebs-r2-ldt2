from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import os

db = SQLAlchemy()


def create_app():
    load_dotenv()
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-r2d2")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///r2ldt2.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    from app.routes.home import home_bp
    from app.routes.configuracion import config_bp
    from app.routes.download_manager import download_bp
    from app.routes.informes import informes_bp
    from app.routes.ayuda import ayuda_bp

    app.register_blueprint(home_bp)
    app.register_blueprint(config_bp, url_prefix="/configuracion")
    app.register_blueprint(download_bp, url_prefix="/download")
    app.register_blueprint(informes_bp, url_prefix="/informes")
    app.register_blueprint(ayuda_bp, url_prefix="/ayuda")

    with app.app_context():
        from app.models import ambiente, usuario_app, tipo_linea, parametro_ldt, aplicacion_ebs, plantilla_ldt  # noqa: F401
        try:
            db.create_all()
        except Exception:
            db.session.rollback()

    return app
