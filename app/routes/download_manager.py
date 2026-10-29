from flask import Blueprint, render_template, request, jsonify
from app.models.ambiente import Ambiente
from app.models.aplicacion_ebs import AplicacionEbs
from app.services.oracle_service import OracleService
from app.services.ldt_service import LdtService

download_bp = Blueprint("download", __name__)


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
    db_user      = (data.get("db_user") or "").strip()
    db_pass      = (data.get("db_pass") or "").strip()
    type_code    = (data.get("type_code") or "").strip()
    app_short    = (data.get("app_short_name") or "").strip() or None
    obj_type     = (data.get("obj_type") or "").strip() or None
    additional_1 = (data.get("additional_1") or "").strip() or None
    additional_2 = (data.get("additional_2") or "").strip() or None
    additional_3 = (data.get("additional_3") or "").strip() or None
    additional_4 = (data.get("additional_4") or "").strip() or None

    if not all([ambiente_id, db_user, db_pass, type_code]):
        return jsonify({"error": "Faltan campos obligatorios: ambiente, usuario, contraseña y tipo"}), 400

    ambiente = Ambiente.query.get(ambiente_id)
    if not ambiente:
        return jsonify({"error": "Ambiente no encontrado"}), 404

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
    db_user     = (data.get("db_user") or "").strip()
    db_pass     = (data.get("db_pass") or "").strip()
    items       = data.get("items", [])

    if not all([ambiente_id, db_user, db_pass]):
        return jsonify({"error": "Faltan credenciales o ambiente"}), 400
    if not items:
        return jsonify({"error": "No hay objetos seleccionados"}), 400

    ambiente = Ambiente.query.get(ambiente_id)
    if not ambiente:
        return jsonify({"error": "Ambiente no encontrado"}), 404

    sentencias = []
    for item in items:
        try:
            sentencia = LdtService.generar_desde_item(item, ambiente, db_user, db_pass)
            sentencias.append({"item": item, "sentencia": sentencia, "ok": True})
        except Exception as e:
            sentencias.append({"item": item, "error": str(e), "ok": False})

    return jsonify({"sentencias": sentencias})


@download_bp.route("/hints/<type_code>")
def hints(type_code):
    """Devuelve los hints de campos adicionales para un tipo de objeto."""
    return jsonify({"hints": LdtService.additional_hints(type_code)})
