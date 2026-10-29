from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app import db
from app.models.ambiente import Ambiente
from app.models.usuario_app import UsuarioApp
from app.models.tipo_linea import TipoLinea
from app.models.parametro_ldt import ParametroLdt
from app.models.aplicacion_ebs import AplicacionEbs
from app.models.plantilla_ldt import PlantillaLdt
from app.services.oracle_service import OracleService
from app.services.ldt_service import LdtService

config_bp = Blueprint("configuracion", __name__)


@config_bp.route("/")
def index():
    return render_template("configuracion/index.html")


# --- Ambientes ---

@config_bp.route("/ambientes")
def ambientes():
    items = Ambiente.query.order_by(Ambiente.nombre).all()
    return render_template("configuracion/ambientes.html", ambientes=items)


@config_bp.route("/ambientes/nuevo", methods=["GET", "POST"])
def ambiente_nuevo():
    if request.method == "POST":
        amb = Ambiente(
            nombre=request.form["nombre"],
            descripcion=request.form.get("descripcion"),
            host=request.form["host"],
            puerto=int(request.form.get("puerto", 1521)),
            service_name=request.form["service_name"],
        )
        db.session.add(amb)
        db.session.commit()
        flash(f'Ambiente "{amb.nombre}" creado correctamente.', "success")
        return redirect(url_for("configuracion.ambientes"))
    return render_template("configuracion/ambiente_form.html", ambiente=None)


@config_bp.route("/ambientes/<int:id>/editar", methods=["GET", "POST"])
def ambiente_editar(id):
    amb = Ambiente.query.get_or_404(id)
    if request.method == "POST":
        amb.nombre = request.form["nombre"]
        amb.descripcion = request.form.get("descripcion")
        amb.host = request.form["host"]
        amb.puerto = int(request.form.get("puerto", 1521))
        amb.service_name = request.form["service_name"]
        db.session.commit()
        flash(f'Ambiente "{amb.nombre}" actualizado.', "success")
        return redirect(url_for("configuracion.ambientes"))
    return render_template("configuracion/ambiente_form.html", ambiente=amb)


@config_bp.route("/ambientes/<int:id>/eliminar", methods=["POST"])
def ambiente_eliminar(id):
    amb = Ambiente.query.get_or_404(id)
    amb.activo = False
    db.session.commit()
    flash(f'Ambiente "{amb.nombre}" desactivado.', "warning")
    return redirect(url_for("configuracion.ambientes"))


@config_bp.route("/ambientes/<int:id>/test", methods=["POST"])
def ambiente_test(id):
    amb = Ambiente.query.get_or_404(id)
    user = request.form.get("test_user")
    pwd = request.form.get("test_pass")
    svc = OracleService(amb, user, pwd)
    ok, msg = svc.test_connection()
    return jsonify({"ok": ok, "message": msg})


# --- Usuarios App ---

@config_bp.route("/usuarios")
def usuarios():
    items = UsuarioApp.query.filter_by(activo=True).order_by(UsuarioApp.username).all()
    ambientes = Ambiente.query.filter_by(activo=True).all()
    return render_template("configuracion/usuarios.html", usuarios=items, ambientes=ambientes)


@config_bp.route("/usuarios/nuevo", methods=["POST"])
def usuario_nuevo():
    u = UsuarioApp(
        username=request.form["username"],
        nombre_completo=request.form.get("nombre_completo"),
        ambiente_id=int(request.form["ambiente_id"]),
    )
    db.session.add(u)
    db.session.commit()
    flash(f'Usuario "{u.username}" agregado.', "success")
    return redirect(url_for("configuracion.usuarios"))


@config_bp.route("/usuarios/<int:id>/eliminar", methods=["POST"])
def usuario_eliminar(id):
    u = UsuarioApp.query.get_or_404(id)
    u.activo = False
    db.session.commit()
    flash(f'Usuario "{u.username}" desactivado.', "warning")
    return redirect(url_for("configuracion.usuarios"))


# --- Tipos de Linea ---

@config_bp.route("/tipos-linea")
def tipos_linea():
    items = TipoLinea.query.order_by(TipoLinea.codigo).all()
    return render_template("configuracion/tipos_linea.html", tipos=items)


@config_bp.route("/tipos-linea/nuevo", methods=["POST"])
def tipo_linea_nuevo():
    t = TipoLinea(
        codigo=request.form["codigo"],
        descripcion=request.form.get("descripcion"),
        extension=request.form["extension"],
    )
    db.session.add(t)
    db.session.commit()
    flash(f'Tipo "{t.codigo}" creado.', "success")
    return redirect(url_for("configuracion.tipos_linea"))


@config_bp.route("/tipos-linea/<int:id>/eliminar", methods=["POST"])
def tipo_linea_eliminar(id):
    t = TipoLinea.query.get_or_404(id)
    t.activo = False
    db.session.commit()
    flash(f'Tipo "{t.codigo}" desactivado.', "warning")
    return redirect(url_for("configuracion.tipos_linea"))


# --- Parametros LDT ---

@config_bp.route("/parametros-ldt")
def parametros_ldt():
    items = ParametroLdt.query.order_by(ParametroLdt.nombre).all()
    return render_template("configuracion/parametros_ldt.html", parametros=items)


@config_bp.route("/parametros-ldt/nuevo", methods=["POST"])
def parametro_ldt_nuevo():
    p = ParametroLdt(
        nombre=request.form["nombre"],
        valor=request.form["valor"],
        descripcion=request.form.get("descripcion"),
    )
    db.session.add(p)
    db.session.commit()
    flash(f'Parametro "{p.nombre}" creado.', "success")
    return redirect(url_for("configuracion.parametros_ldt"))


@config_bp.route("/parametros-ldt/<int:id>/eliminar", methods=["POST"])
def parametro_ldt_eliminar(id):
    p = ParametroLdt.query.get_or_404(id)
    p.activo = False
    db.session.commit()
    flash(f'Parametro "{p.nombre}" desactivado.', "warning")
    return redirect(url_for("configuracion.parametros_ldt"))


# --- Plantillas FNDLOAD ---

@config_bp.route("/plantillas-ldt")
def plantillas_ldt():
    plantillas = PlantillaLdt.query.order_by(
        PlantillaLdt.codigo_tipo, PlantillaLdt.secuencia
    ).all()
    tipos = LdtService.tipos_disponibles()
    return render_template("configuracion/plantillas_ldt.html",
                           plantillas=plantillas, tipos=tipos)


@config_bp.route("/plantillas-ldt/nueva", methods=["POST"])
def plantilla_ldt_nueva():
    p = PlantillaLdt(
        secuencia=int(request.form.get("secuencia", 10)),
        codigo_tipo=request.form["codigo_tipo"].strip().upper(),
        tipo_ejec=request.form.get("tipo_ejec", "DOWNLOAD").strip().upper(),
        ejecutable=request.form["ejecutable"].strip(),
        habilitado=(request.form.get("habilitado") == "on"),
        **{f"parametro_{i}": request.form.get(f"parametro_{i}", "").strip() or None
           for i in range(1, 11)},
    )
    db.session.add(p)
    db.session.commit()
    flash(f'Plantilla para "{p.codigo_tipo}" (seq {p.secuencia}) creada.', "success")
    return redirect(url_for("configuracion.plantillas_ldt"))


@config_bp.route("/plantillas-ldt/<int:id>/editar", methods=["GET", "POST"])
def plantilla_ldt_editar(id):
    p = PlantillaLdt.query.get_or_404(id)
    if request.method == "POST":
        p.secuencia  = int(request.form.get("secuencia", 10))
        p.codigo_tipo = request.form["codigo_tipo"].strip().upper()
        p.tipo_ejec  = request.form.get("tipo_ejec", "DOWNLOAD").strip().upper()
        p.ejecutable  = request.form["ejecutable"].strip()
        p.habilitado  = (request.form.get("habilitado") == "on")
        for i in range(1, 11):
            setattr(p, f"parametro_{i}",
                    request.form.get(f"parametro_{i}", "").strip() or None)
        db.session.commit()
        flash("Plantilla actualizada.", "success")
        return redirect(url_for("configuracion.plantillas_ldt"))
    tipos = LdtService.tipos_disponibles()
    return render_template("configuracion/plantilla_ldt_form.html", plantilla=p, tipos=tipos)


@config_bp.route("/plantillas-ldt/<int:id>/eliminar", methods=["POST"])
def plantilla_ldt_eliminar(id):
    p = PlantillaLdt.query.get_or_404(id)
    db.session.delete(p)
    db.session.commit()
    flash("Plantilla eliminada.", "warning")
    return redirect(url_for("configuracion.plantillas_ldt"))


@config_bp.route("/plantillas-ldt/<int:id>/toggle", methods=["POST"])
def plantilla_ldt_toggle(id):
    p = PlantillaLdt.query.get_or_404(id)
    p.habilitado = not p.habilitado
    db.session.commit()
    return jsonify({"habilitado": p.habilitado})


# --- Aplicaciones EBS ---

@config_bp.route("/aplicaciones-ebs")
def aplicaciones_ebs():
    items = AplicacionEbs.query.order_by(AplicacionEbs.short_name).all()
    return render_template("configuracion/aplicaciones_ebs.html", aplicaciones=items)


@config_bp.route("/aplicaciones-ebs/nuevo", methods=["POST"])
def aplicacion_ebs_nueva():
    a = AplicacionEbs(
        short_name=request.form["short_name"].upper(),
        nombre=request.form["nombre"],
        descripcion=request.form.get("descripcion"),
    )
    db.session.add(a)
    db.session.commit()
    flash(f'Aplicacion "{a.short_name}" agregada.', "success")
    return redirect(url_for("configuracion.aplicaciones_ebs"))


@config_bp.route("/aplicaciones-ebs/<int:id>/eliminar", methods=["POST"])
def aplicacion_ebs_eliminar(id):
    a = AplicacionEbs.query.get_or_404(id)
    a.activo = False
    db.session.commit()
    flash(f'Aplicacion "{a.short_name}" desactivada.', "warning")
    return redirect(url_for("configuracion.aplicaciones_ebs"))
