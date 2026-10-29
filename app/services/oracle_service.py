import json
import os

try:
    import oracledb
    # Thick mode: soporta verifiers 10g (0x939), 11g y 12c
    # Solo se inicializa una vez; si ya fue inicializado se ignora el error
    try:
        oracledb.init_oracle_client()
    except oracledb.ProgrammingError:
        pass  # ya inicializado en otro worker
    except Exception:
        pass  # Instant Client no disponible, cae a thin mode
    ORACLEDB_AVAILABLE = True
except ImportError:
    oracledb = None
    ORACLEDB_AVAILABLE = False

from app.models.ambiente import Ambiente


class OracleService:
    """Gestiona conexiones a Oracle EBS por ambiente (thin mode, sin Instant Client)."""

    def __init__(self, ambiente: Ambiente, username: str, password: str):
        self.ambiente = ambiente
        self.username = username
        self.password = password

    def dsn(self):
        return f"{self.ambiente.host}:{self.ambiente.puerto}/{self.ambiente.service_name}"

    def _connect(self):
        if not ORACLEDB_AVAILABLE:
            raise RuntimeError("El driver oracledb no está instalado.")
        return oracledb.connect(user=self.username, password=self.password, dsn=self.dsn())

    def test_connection(self):
        try:
            conn = self._connect()
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM DUAL")
            conn.close()
            return True, "Conexión exitosa"
        except Exception as e:
            return False, str(e)

    def get_fnd_objects(self, type_code: str, type_desc: str, app_short_name: str,
                        obj_type: str, additional_1=None, additional_2=None,
                        additional_3=None, additional_4=None) -> dict:
        """
        Llama a xx_apx_olt_utils_pk.getFndObjects y devuelve el dict parseado del JSON.
        p_additional_4 no tiene DEFAULT en el spec, siempre se pasa (como None si vacío).
        """
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                result = cur.callfunc(
                    "xx_apx_olt_utils_pk.getFndObjects",
                    oracledb.DB_TYPE_CLOB,
                    [
                        type_code,
                        type_desc,
                        app_short_name or None,
                        obj_type or None,
                        additional_1 or None,
                        additional_2 or None,
                        additional_3 or None,
                        additional_4 or None,
                    ],
                )
                json_str = result.read() if hasattr(result, "read") else (result or "{}")
                return json.loads(json_str)
        finally:
            conn.close()

    def get_fnd_apps(self) -> dict:
        """Llama a xx_apx_olt_utils_pk.getFndApps."""
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                result = cur.callfunc(
                    "xx_apx_olt_utils_pk.getFndApps",
                    oracledb.DB_TYPE_CLOB,
                    [],
                )
                json_str = result.read() if hasattr(result, "read") else (result or "{}")
                return json.loads(json_str)
        finally:
            conn.close()
