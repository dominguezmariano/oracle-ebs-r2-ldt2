from app.models.ambiente import Ambiente


TIPOS_OBJETO = {
    "LOOKUPS":            "Lookup Types",
    "CONCPROG":           "Concurrent Programs",
    "RESPONSIBILITIES":   "Responsibilities",
    "ALERTS":             "Alerts",
    "VALUESETS":          "Value Sets",
    "MENU":               "Menus",
    "DESCFLEXS":          "Descriptive Flexfields",
    "FNDMSGS":            "FND Messages",
    "FORMPERS":           "Form Personalizations",
    "MENU_ENTRY":         "Menu Entries",
    "DESCFLEXS_CTXT_ATT": "DFF Context Attributes",
    "DESCFLEXS_CTXT":     "DFF Contexts",
    "PROFILES":           "Profile Options",
    "REQUESTGRP":         "Request Groups",
    "REQUESTGRPU":        "Request Group Units",
    "FUNCTIONS":          "Form Functions",
    "FORMS":              "Forms",
    "KEYFLEXS":           "Key Flexfields",
    "XDOTMLP":            "XDO Data Sources",
    "REQSETLNK":          "Request Sets",
}

ADDITIONAL_HINTS = {
    "FORMPERS":           ["Secuencia", "Nombre del Form", "", ""],
    "MENU_ENTRY":         ["Menú padre", "Function Name", "Sub-menu", "Entry Sequence"],
    "PROFILES":           ["Nivel (RESPONSIBILITY/APPLICATION)", "Valor del nivel",
                           "Mostrar valores (Y/N)", "Valor del profile"],
    "REQUESTGRPU":        ["Tipo de unidad (P/S/A)", "Nombre programa/set", "", ""],
    "DESCFLEXS_CTXT":     ["Context Code", "", "", ""],
    "DESCFLEXS_CTXT_ATT": ["Context Code", "End User Column", "Application Column", "Column Seq Num"],
}

# Comodines disponibles en plantillas:
#   %OBJECT_NAME%     → item['OBJ_TYPE']  (clave usada en FNDLOAD)
#   %OBJ_NAME%        → item['OBJ_NAME']  (nombre legible)
#   %APPL_SHORT_NAME% → item['APP_SHORT_NAME']
#   %OBJ_DESC%        → item['OBJ_DESC']
#   %ADDITIONAL_1..4% → item['ADDITIONAL_1'..'4']
#   $dbUser/$dbPass   → user/pass@host:port/service  (forma corta)
#   %DB_USER%         → usuario DB
#   %DB_PASS%         → contraseña DB
#   %DB_DSN%          → host:port/service


def _reemplazar(texto: str, item: dict, ambiente: Ambiente,
                db_user: str, db_pass: str) -> str:
    if not texto:
        return ""
    dsn = f"{ambiente.host}:{ambiente.puerto}/{ambiente.service_name}"
    replacements = {
        "%DB_USER%":         db_user,
        "%DB_PASS%":         db_pass,
        "%DB_DSN%":          dsn,
        "%OBJECT_NAME%":     item.get("OBJ_TYPE") or "",
        "%OBJ_NAME%":        item.get("OBJ_NAME") or "",
        "%APPL_SHORT_NAME%": item.get("APP_SHORT_NAME") or "",
        "%OBJ_DESC%":        item.get("OBJ_DESC") or "",
        "%ADDITIONAL_1%":    item.get("ADDITIONAL_1") or "",
        "%ADDITIONAL_2%":    item.get("ADDITIONAL_2") or "",
        "%ADDITIONAL_3%":    item.get("ADDITIONAL_3") or "",
        "%ADDITIONAL_4%":    item.get("ADDITIONAL_4") or "",
    }
    for token, valor in replacements.items():
        texto = texto.replace(token, valor)
    return texto


class LdtService:

    @staticmethod
    def tipos_disponibles() -> dict:
        return TIPOS_OBJETO

    @staticmethod
    def additional_hints(type_code: str) -> list:
        return ADDITIONAL_HINTS.get(type_code, ["", "", "", ""])

    @staticmethod
    def generar_desde_item(item: dict, ambiente: Ambiente,
                           db_user: str, db_pass: str) -> str:
        """
        Genera las sentencias FNDLOAD para un item usando las PlantillaLdt
        configuradas en la BD para su tipo de objeto.
        Devuelve un string con una o más líneas (según las secuencias habilitadas).
        """
        from app.models.plantilla_ldt import PlantillaLdt

        type_code = item.get("OBJ_CODE", "")
        plantillas = (
            PlantillaLdt.query
            .filter_by(codigo_tipo=type_code, habilitado=True)
            .order_by(PlantillaLdt.secuencia)
            .all()
        )

        if not plantillas:
            raise ValueError(
                f"No hay plantillas habilitadas para el tipo '{type_code}'. "
                f"Configurálas en Configuración › Plantillas FNDLOAD."
            )

        lineas = []
        for pl in plantillas:
            partes = [pl.ejecutable]
            for param in pl.parametros():
                partes.append(_reemplazar(param, item, ambiente, db_user, db_pass))
            lineas.append(" ".join(partes))

        return "\n".join(lineas)
