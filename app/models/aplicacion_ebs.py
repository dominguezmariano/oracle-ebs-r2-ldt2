from app import db
from datetime import datetime


class AplicacionEbs(db.Model):
    __tablename__ = "aplicaciones_ebs"

    id = db.Column(db.Integer, primary_key=True)
    short_name = db.Column(db.String(50), nullable=False, unique=True)
    nombre = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.String(300))
    activo = db.Column(db.Boolean, default=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<AplicacionEbs {self.short_name}>"
