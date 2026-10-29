from app import db
from datetime import datetime


class ParametroLdt(db.Model):
    __tablename__ = "parametros_ldt"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    valor = db.Column(db.Text, nullable=False)
    descripcion = db.Column(db.String(300))
    activo = db.Column(db.Boolean, default=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<ParametroLdt {self.nombre}>"
