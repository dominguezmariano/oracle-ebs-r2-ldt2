import re
from flask import Blueprint, render_template, request, jsonify, send_file
import io

from app.models.ambiente import Ambiente
from app.models.aplicacion_ebs import AplicacionEbs
from app.models.plantilla_ldt import PlantillaLdt
from app.models.tipo_linea import TipoLinea
from app.services import credenciales
from app.services.oracle_service import OracleService
from app.services.ldt_service import LdtService
from app.services.ldt_generator import LdtGenerator

download_bp = Blueprint("download", __name__)

# Mapping: OBJ_CODE → {LCT root KEY field → item field name}
# None means pass None (let the SQL filter be skipped)
_TYPE_KEY_MAP = {
    'LOOKUPS': {
        'VIEW_APPSNAME': 'APP_SHORT_NAME',
        'LOOKUP_TYPE': 'OBJ_TYPE',          # OBJ_TYPE = código técnico (XX_AR_FE_INCOTERMS)
        'APPLICATION_SHORT_NAME': None,
        'SECURITY_GROUP': None,
    },
    'CONCPROG': {
        'CONCURRENT_PROGRAM_NAME': 'OBJ_TYPE',  # OBJ_TYPE = código técnico (XXARAPLI)
        'APPLICATION_SHORT_NAME': 'APP_SHORT_NAME',
        # Params derivados — calculados a partir de los anteriores
        '_DERIVE': {
            # EXECUTABLE suele tener el mismo nombre que el programa
            'EXECUTABLE_NAME': lambda p: p.get('CONCURRENT_PROGRAM_NAME'),
            # El DFF SRS siempre se llama $SRS$.<program_name>
            'DESCRIPTIVE_FLEXFIELD_NAME': lambda p: '$SRS$.' + (p.get('CONCURRENT_PROGRAM_NAME') or ''),
        },
    },
}


def _item_to_lct_params(item: dict) -> dict:
    """Map a getFndObjects item dict to LCT DOWNLOAD bind variables."""
    obj_code = (item.get('OBJ_CODE') or '').upper()
    mapping = _TYPE_KEY_MAP.get(obj_code)
    if not mapping:
        return {}
    params = {
        k: item.get(v) if v else None
        for k, v in mapping.items()
        if k != '_DERIVE'
    }
    for key, fn in (mapping.get('_DERIVE') or {}).items():
        params[key] = fn(params)
    return params


def _extract_lct_filename(plantillas) -> str | None:
    """Extract LCT filename from PlantillaLdt parameter values."""
    for pl in plantillas:
        for p in pl.parametros():
            m = re.search(r'import/([^/\s\'"]+\.lct)', p)
            if m:
                return m.group(1)
    return None


def _extract_filename_template(plantillas) -> str | None:
    """
    Return the output filename template from parametro_4 of the first matching
    PlantillaLdt.  The template may contain %OBJECT_NAME%, %APPL_SHORT_NAME%,
    %OBJ_NAME%, and %LANG% comodines.
    If parametro_4 contains a path (e.g. $FND_TOP/…/file.cnc) only the
    filename portion after the last '/' is used.  Surrounding quotes are stripped.
    """
    for pl in plantillas:
        p4 = (pl.parametro_4 or '').strip()
        if not p4:
            continue
        if '/' in p4:
            p4 = p4.rsplit('/', 1)[1]
        p4 = p4.strip('"\'')
        if p4 and re.search(r'\.\w+$', p4):
            return p4
    return None


def _render_filename(template: str, obj_type: str, app_short: str, lang: str) -> str:
    """Apply comodines to an output filename template.

    Supports %OBJECT_NAME%, %OBJ_NAME%, %APPL_SHORT_NAME%, %LANG%.
    If the template has no %LANG% comodin, falls back to replacing the embedded
    base-language code 'US' (FNDLOAD convention: parametro_4 often stores the US
    filename literally, e.g. PROGRAM_CP_US.cnc, and the language is swapped per run).
    """
    result = template
    result = result.replace('%OBJECT_NAME%', obj_type)
    result = result.replace('%OBJ_NAME%', obj_type)
    result = result.replace('%APPL_SHORT_NAME%', app_short or '')
    if '%LANG%' in result:
        result = result.replace('%LANG%', lang)
    elif lang != 'US':
        # Replace _US. or _US at end-of-stem with _{lang}
        result = re.sub(r'(?<=[_\-])US(?=[_\-.]|$)', lang, result)
    return re.sub(r'[^A-Za-z0-9_\-.]', '_', result)


def _credenciales(ambiente, data):
    """(user, pass, desde_servidor) — override manual del cliente o secrets del servidor."""
    return credenciales.resolver(
        ambiente,
        (data.get("db_user") or "").strip(),
        (data.get("db_pass") or "").strip(),
    )


_ERR_CREDS = ("El ambiente no tiene credenciales configuradas. Definí el usuario en "
              "Configuración › Ambientes y la password en los secrets del servidor, "
              "o ingresalas manualmente.")


@download_bp.route("/")
def index():
    ambientes = Ambiente.query.filter_by(activo=True).order_by(Ambiente.nombre).all()
    aplicaciones = AplicacionEbs.query.filter_by(activo=True).order_by(AplicacionEbs.short_name).all()
    tipos = LdtService.tipos_disponibles()
    return render_template(
        "download_manager.html",
        ambientes=ambientes,
        aplicaciones=aplicaciones,
        tipos=tipos,
    )


@download_bp.route("/buscar", methods=["POST"])
def buscar():
    """Llama a getFndObjects en Oracle y devuelve los items encontrados."""
    data = request.get_json() or request.form
    ambiente_id  = data.get("ambiente_id")
    type_code    = (data.get("type_code") or "").strip()
    app_short    = (data.get("app_short_name") or "").strip() or None
    obj_type     = (data.get("obj_type") or "").strip() or None
    additional_1 = (data.get("additional_1") or "").strip() or None
    additional_2 = (data.get("additional_2") or "").strip() or None
    additional_3 = (data.get("additional_3") or "").strip() or None
    additional_4 = (data.get("additional_4") or "").strip() or None

    if not all([ambiente_id, type_code]):
        return jsonify({"error": "Faltan campos obligatorios: ambiente y tipo"}), 400

    ambiente = Ambiente.query.get(ambiente_id)
    if not ambiente:
        return jsonify({"error": "Ambiente no encontrado"}), 404

    db_user, db_pass, _ = _credenciales(ambiente, data)
    if not db_user:
        return jsonify({"error": _ERR_CREDS}), 400

    tipos = LdtService.tipos_disponibles()
    type_desc = tipos.get(type_code, type_code)

    svc = OracleService(ambiente, db_user, db_pass)
    try:
        result = svc.get_fnd_objects(
            type_code=type_code,
            type_desc=type_desc,
            app_short_name=app_short,
            obj_type=obj_type,
            additional_1=additional_1,
            additional_2=additional_2,
            additional_3=additional_3,
            additional_4=additional_4,
        )
        if "errors" in result:
            return jsonify({"error": result["errors"][0].get("message", "Error en Oracle")}), 500

        return jsonify({"items": result.get("items", []), "total": len(result.get("items", []))})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@download_bp.route("/generar", methods=["POST"])
def generar():
    """
    Recibe lista de items seleccionados y credenciales Oracle,
    devuelve las sentencias FNDLOAD generadas.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Payload JSON requerido"}), 400

    ambiente_id = data.get("ambiente_id")
    items       = data.get("items", [])

    if not ambiente_id:
        return jsonify({"error": "Falta el ambiente"}), 400
    if not items:
        return jsonify({"error": "No hay objetos seleccionados"}), 400

    ambiente = Ambiente.query.get(ambiente_id)
    if not ambiente:
        return jsonify({"error": "Ambiente no encontrado"}), 404

    db_user, db_pass, desde_servidor = _credenciales(ambiente, data)
    if not db_user:
        return jsonify({"error": _ERR_CREDS}), 400
    if desde_servidor:
        # Estas sentencias viajan al navegador: la password del servidor nunca se incluye.
        db_pass = "$dbPass"

    sentencias = []
    for item in items:
        try:
            sentencia = LdtService.generar_desde_item(item, ambiente, db_user, db_pass)
            sentencias.append({"item": item, "sentencia": sentencia, "ok": True})
        except Exception as e:
            sentencias.append({"item": item, "error": str(e), "ok": False})

    return jsonify({"sentencias": sentencias})


@download_bp.route("/generar_ldt", methods=["POST"])
def generar_ldt():
    """
    Genera archivos LDT reales consultando Oracle + leyendo el LCT local.
    Devuelve un ZIP con un archivo .ldt por idioma instalado en la instancia.
    """
    import zipfile as zfmod

    data = request.get_json()
    if not data:
        return jsonify({"error": "Payload JSON requerido"}), 400

    ambiente_id = data.get("ambiente_id")
    items       = data.get("items", [])

    if not ambiente_id:
        return jsonify({"error": "Falta el ambiente"}), 400
    if not items:
        return jsonify({"error": "No hay objetos seleccionados"}), 400

    ambiente = Ambiente.query.get(ambiente_id)
    if not ambiente:
        return jsonify({"error": "Ambiente no encontrado"}), 404

    db_user, db_pass, _ = _credenciales(ambiente, data)
    if not db_user:
        return jsonify({"error": _ERR_CREDS}), 400

    svc = OracleService(ambiente, db_user, db_pass)
    gen = LdtGenerator()
    errors = []
    zip_buf = io.BytesIO()

    try:
        conn = svc.connect()
    except Exception as e:
        return jsonify({"error": f"No se pudo conectar a Oracle: {e}"}), 500

    try:
        languages = gen._get_installed_languages(conn)

        with zfmod.ZipFile(zip_buf, 'w', zfmod.ZIP_DEFLATED) as zf:
            for item in items:
                obj_code = (item.get('OBJ_CODE') or '').upper()
                obj_type = item.get('OBJ_TYPE') or item.get('OBJ_NAME') or 'objeto'
                obj_name = item.get('OBJ_NAME') or obj_type
                safe_name = re.sub(r'[^A-Za-z0-9_\-]', '_', obj_type)

                tipo = TipoLinea.query.filter_by(codigo=obj_code).first()
                ext = (tipo.extension if tipo else '.ldt').lstrip('.')

                # Always query PlantillaLdt — for LCT filename (fallback) and
                # for the output filename template stored in parametro_4.
                plantillas = PlantillaLdt.query.filter_by(
                    codigo_tipo=obj_code, habilitado=True
                ).order_by(PlantillaLdt.secuencia).all()

                lct_filename = tipo.lct_filename if tipo else None
                if not lct_filename:
                    lct_filename = _extract_lct_filename(plantillas)

                if not lct_filename:
                    errors.append(f"{obj_name}: no se encontró LCT (configuralo en Tipos de Línea o en PlantillaLdt)")
                    continue

                filename_template = _extract_filename_template(plantillas)
                app_short = item.get('APP_SHORT_NAME', '')

                root_params = _item_to_lct_params(item)
                if not root_params:
                    errors.append(f"{obj_name}: tipo '{obj_code}' no tiene mapeo de parámetros LCT definido")
                    continue

                for lang in languages:
                    try:
                        ldt_content = gen.generate(lct_filename, root_params, conn, lang)
                        if filename_template:
                            fname = _render_filename(filename_template, obj_type, app_short, lang)
                        else:
                            fname = f'{safe_name}_{lang}.{ext}'
                        zf.writestr(fname, ldt_content)
                    except Exception as e:
                        errors.append(f"{obj_name} [{lang}]: {e}")

            if errors:
                zf.writestr('_errores.txt', '\n'.join(errors))

    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500

    conn.close()
    zip_buf.seek(0)
    return send_file(zip_buf, mimetype='application/zip',
                     as_attachment=True, download_name='ldt_generados.zip')


@download_bp.route("/hints/<type_code>")
def hints(type_code):
    """Devuelve los hints de campos adicionales para un tipo de objeto."""
    return jsonify({"hints": LdtService.additional_hints(type_code)})
