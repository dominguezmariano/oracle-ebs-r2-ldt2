from app import db
from datetime import datetime


class TipoLinea(db.Model):
    __tablename__ = "tipos_linea"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), nullable=False, unique=True)
    descripcion = db.Column(db.String(200))
    extension = db.Column(db.String(20), nullable=False)
    activo = db.Column(db.Boolean, default=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<TipoLinea {self.codigo}>"
