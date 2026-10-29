from flask import Blueprint, render_template

informes_bp = Blueprint("informes", __name__)


@informes_bp.route("/")
def index():
    return render_template("informes.html")
