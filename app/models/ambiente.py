from app import db
from datetime import datetime


class Ambiente(db.Model):
    __tablename__ = "ambientes"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False, unique=True)
    descripcion = db.Column(db.String(200))
    host = db.Column(db.String(200), nullable=False)
    puerto = db.Column(db.Integer, default=1521)
    service_name = db.Column(db.String(100), nullable=False)
    activo = db.Column(db.Boolean, default=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Ambiente {self.nombre}>"

    def to_dict(self):
        return {
            "id": self.id,
            "nombre": self.nombre,
            "descripcion": self.descripcion,
            "host": self.host,
            "puerto": self.puerto,
            "service_name": self.service_name,
            "activo": self.activo,
        }
