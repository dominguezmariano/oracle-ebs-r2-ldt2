"""
Resolución de credenciales de DB por ambiente.

El usuario se guarda en la tabla `ambientes` (columna db_user). La contraseña
NUNCA se guarda en la base ni se envía al navegador: se lee de secrets del
servidor, buscando en este orden:

  1. Variable EBS_DB_PASSWORD_<CLAVE>_FILE  -> ruta a un archivo con la password
  2. Variable EBS_DB_PASSWORD_<CLAVE>       -> la password (típico: secrets.env)
  3. Archivo /run/secrets/ebs_db_password_<clave>   (Docker secrets)

<CLAVE> es el nombre del ambiente en mayúsculas con todo lo que no sea
letra/número reemplazado por "_" (ej: "TEST-FIX" -> TEST_FIX).
"""
import os
import re

SECRETS_DIR = os.getenv("SECRETS_DIR", "/run/secrets")


def clave_ambiente(nombre: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", (nombre or "").upper()).strip("_")


def nombre_variable(nombre_ambiente: str) -> str:
    return f"EBS_DB_PASSWORD_{clave_ambiente(nombre_ambiente)}"


def _leer_archivo(ruta: str) -> str | None:
    try:
        with open(ruta, encoding="utf-8") as f:
            valor = f.read().strip()
        return valor or None
    except OSError:
        return None


def obtener_password(nombre_ambiente: str) -> str | None:
    var = nombre_variable(nombre_ambiente)

    ruta = os.getenv(f"{var}_FILE")
    if ruta:
        valor = _leer_archivo(ruta)
        if valor:
            return valor

    valor = os.getenv(var)
    if valor:
        return valor

    return _leer_archivo(os.path.join(SECRETS_DIR, var.lower()))


def tiene_credenciales(ambiente) -> bool:
    return bool(ambiente.db_user and obtener_password(ambiente.nombre))


def resolver(ambiente, user_cliente: str = "", pass_cliente: str = ""):
    """
    Devuelve (usuario, password, desde_servidor).
    Si el cliente envía usuario y password, tienen prioridad (override manual).
    Si no, se usan el usuario del ambiente y la password de los secrets.
    Devuelve (None, None, False) si no hay credenciales disponibles.
    """
    if user_cliente and pass_cliente:
        return user_cliente, pass_cliente, False
    if ambiente.db_user:
        pwd = obtener_password(ambiente.nombre)
        if pwd:
            return ambiente.db_user, pwd, True
    return None, None, False
