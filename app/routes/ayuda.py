from flask import Blueprint, render_template

ayuda_bp = Blueprint("ayuda", __name__)


@ayuda_bp.route("/")
def index():
    return render_template("ayuda.html")
