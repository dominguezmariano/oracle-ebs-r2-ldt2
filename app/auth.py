"""
Autenticación SSO Despegar (ATP3 / OIDC authorization code).

Se activa con AUTH_ENABLED=true. Con AUTH_ENABLED=false (default) no se
contacta a ATP3: todas las requests corren como el usuario AUTH_DEV_USER,
útil para desarrollo y pruebas locales.

Flujo (mismo patrón que oracle-ebs-arba):
  1. GET /auth/login   -> redirige a {ATP3_AUTH_URL}/authorization
  2. ATP3 vuelve a /?code=...  -> se intercambia el code en ATP3_TOKEN_URL
  3. Se lee el email del id_token, se valida el dominio y se guarda en la
     sesión Flask (cookie firmada, httponly).
  4. before_request exige sesión en todo salvo las rutas públicas.

Permisos: si AUTH_ADMINS (emails separados por coma) está definido, solo esos
usuarios acceden a /configuracion. Si está vacío, no hay restricción por rol.
"""
import logging
import os
from urllib.parse import urlencode

from flask import (Blueprint, current_app, g, jsonify, redirect, render_template_string,
                   request, session, url_for)

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

# Endpoints accesibles sin sesión
PUBLIC_ENDPOINTS = {"auth.login", "auth.logout", "static"}
# Blueprints que requieren rol admin (cuando AUTH_ADMINS está definido)
ADMIN_BLUEPRINTS = {"configuracion"}


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def load_auth_config(app) -> None:
    """Lee la configuración de auth desde variables de entorno."""
    app.config["AUTH_ENABLED"] = _bool("AUTH_ENABLED", False)
    app.config["AUTH_DEV_USER"] = os.getenv("AUTH_DEV_USER", "dev-local@despegar.com")
    app.config["AUTH_ADMINS"] = {
        e.strip().lower() for e in os.getenv("AUTH_ADMINS", "").split(",") if e.strip()
    }
    app.config["ATP3_CLIENT_ID"] = os.getenv("ATP3_CLIENT_ID", "")
    app.config["ATP3_CLIENT_SECRET"] = os.getenv("ATP3_CLIENT_SECRET", "")
    app.config["ATP3_AUTH_URL"] = os.getenv("ATP3_AUTH_URL", "https://auth.despegar.com")
    app.config["ATP3_TOKEN_URL"] = os.getenv(
        "ATP3_TOKEN_URL", "https://auth-core.us-east-1.despegar.net/token")
    app.config["ATP3_CA_BUNDLE"] = os.getenv("ATP3_CA_BUNDLE", "")
    app.config["OIDC_ALLOWED_EMAIL_DOMAIN"] = os.getenv("OIDC_ALLOWED_EMAIL_DOMAIN", "despegar.com")
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = _bool("SESSION_COOKIE_SECURE", False)
    app.config["PERMANENT_SESSION_LIFETIME"] = int(float(os.getenv("AUTH_SESSION_HOURS", "6")) * 3600)

    if app.config["AUTH_ENABLED"]:
        missing = [k for k in ("ATP3_CLIENT_ID", "ATP3_CLIENT_SECRET") if not app.config[k]]
        if missing:
            raise RuntimeError(f"AUTH_ENABLED=true pero faltan variables: {', '.join(missing)}")
        if app.config["SECRET_KEY"] in ("dev-secret-r2d2", "change-me-in-production"):
            logger.warning("AUTH_ENABLED=true con SECRET_KEY por defecto: definí un SECRET_KEY real.")
    else:
        logger.warning("Autenticación DESACTIVADA (AUTH_ENABLED=false): "
                       "todas las requests corren como %s", app.config["AUTH_DEV_USER"])


def is_admin(email: str) -> bool:
    admins = current_app.config["AUTH_ADMINS"]
    return not admins or (email or "").lower() in admins


def _wants_json() -> bool:
    return (request.method != "GET" or request.is_json
            or "application/json" in request.headers.get("Accept", ""))


def _oidc_params() -> dict:
    return {
        "client_id": current_app.config["ATP3_CLIENT_ID"],
        "response_type": "code",
        "scope": "openid u:name",
        "redirect_uri": url_for("home.index", _external=True),
    }


def _exchange_code(code: str) -> dict:
    import requests
    cfg = current_app.config
    bundle = cfg["ATP3_CA_BUNDLE"]
    r = requests.post(
        cfg["ATP3_TOKEN_URL"],
        data={
            "client_id": cfg["ATP3_CLIENT_ID"],
            "client_secret": cfg["ATP3_CLIENT_SECRET"],
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": url_for("home.index", _external=True),
        },
        verify=bundle if bundle and os.path.exists(bundle) else True,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def _email_from_id_token(id_token: str) -> tuple[str, str]:
    import jwt
    # El token llega directo del endpoint de ATP3 por TLS verificado,
    # por eso solo se leen los claims (igual que oracle-ebs-arba).
    claims = jwt.decode(id_token, options={"verify_signature": False})
    sub = claims.get("sub", "")
    email = claims.get("email")
    if not email:
        user = sub.split("@")[0] if "@" in sub else sub
        email = sub if "@" in sub and "@ar.infra.d" not in sub and "@despegar" not in sub \
            else f"{user}@despegar.com"
    return sub, email


def _forbidden(msg: str, code: int):
    return render_template_string(
        "<h2>{{ msg }}</h2><p><a href='{{ url_for('auth.logout') }}'>Cerrar sesión</a></p>",
        msg=msg), code


def _handle_callback(code: str):
    try:
        token_data = _exchange_code(code)
    except Exception:
        logger.exception("Falló el intercambio de code con ATP3")
        return _forbidden("No se pudo completar el login con ATP3.", 502)

    id_token = token_data.get("id_token")
    if not id_token:
        logger.error("ATP3 no devolvió id_token. Keys: %s", list(token_data.keys()))
        return _forbidden("Login fallido (sin id_token).", 401)

    sub, email = _email_from_id_token(id_token)
    domain = current_app.config["OIDC_ALLOWED_EMAIL_DOMAIN"]
    if domain and not email.lower().endswith(f"@{domain.lower()}"):
        logger.warning("Login rechazado: %s no termina en @%s", email, domain)
        return _forbidden(f"Solo usuarios @{domain} pueden acceder.", 403)

    session.clear()
    session.permanent = True
    session["user_email"] = email
    session["user_sub"] = sub
    logger.info("Login OK: %s", email)
    return redirect(url_for("home.index"))


@auth_bp.route("/auth/login")
def login():
    if not current_app.config["AUTH_ENABLED"]:
        return redirect(url_for("home.index"))
    return redirect(f"{current_app.config['ATP3_AUTH_URL']}/authorization?{urlencode(_oidc_params())}")


@auth_bp.route("/auth/logout")
def logout():
    session.clear()
    if not current_app.config["AUTH_ENABLED"]:
        return redirect(url_for("home.index"))
    return redirect(f"{current_app.config['ATP3_AUTH_URL']}/signout?{urlencode(_oidc_params())}")


def init_auth(app) -> None:
    load_auth_config(app)
    app.register_blueprint(auth_bp)

    @app.before_request
    def _require_login():
        if not app.config["AUTH_ENABLED"]:
            g.user_email = app.config["AUTH_DEV_USER"]
            g.is_admin = True
            return None

        # Callback OIDC: ATP3 vuelve a "/" con ?code=
        if request.endpoint == "home.index" and request.args.get("code"):
            return _handle_callback(request.args["code"])

        if request.endpoint in PUBLIC_ENDPOINTS:
            return None

        email = session.get("user_email")
        if not email:
            if _wants_json():
                return jsonify({"error": "No autenticado"}), 401
            return redirect(url_for("auth.login"))

        g.user_email = email
        g.is_admin = is_admin(email)
        if request.blueprint in ADMIN_BLUEPRINTS and not g.is_admin:
            if _wants_json():
                return jsonify({"error": "Sin permisos"}), 403
            return _forbidden("No tenés permisos para acceder a Configuración.", 403)
        return None

    @app.context_processor
    def _inject_user():
        return {
            "current_user": getattr(g, "user_email", None),
            "current_is_admin": getattr(g, "is_admin", False),
            "auth_enabled": app.config["AUTH_ENABLED"],
        }
