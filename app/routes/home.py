from flask import Blueprint, render_template
from app.models.ambiente import Ambiente
from app.models.usuario_app import UsuarioApp

home_bp = Blueprint("home", __name__)


@home_bp.route("/")
def index():
    total_ambientes = Ambiente.query.filter_by(activo=True).count()
    total_usuarios = UsuarioApp.query.filter_by(activo=True).count()
    return render_template("home.html", total_ambientes=total_ambientes, total_usuarios=total_usuarios)
