from app import db
from datetime import datetime


class PlantillaLdt(db.Model):
    __tablename__ = "plantillas_ldt"

    id           = db.Column(db.Integer, primary_key=True)
    secuencia    = db.Column(db.Integer, nullable=False, default=10)
    codigo_tipo  = db.Column(db.String(50), nullable=False, index=True)
    tipo_ejec    = db.Column(db.String(20), nullable=False, default="DOWNLOAD")
    ejecutable   = db.Column(db.String(50), nullable=False)
    parametro_1  = db.Column(db.String(500))
    parametro_2  = db.Column(db.String(500))
    parametro_3  = db.Column(db.String(500))
    parametro_4  = db.Column(db.String(500))
    parametro_5  = db.Column(db.String(500))
    parametro_6  = db.Column(db.String(500))
    parametro_7  = db.Column(db.String(500))
    parametro_8  = db.Column(db.String(500))
    parametro_9  = db.Column(db.String(500))
    parametro_10 = db.Column(db.String(500))
    habilitado   = db.Column(db.Boolean, default=True, nullable=False)
    creado_en    = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<PlantillaLdt {self.codigo_tipo} seq={self.secuencia}>"

    def parametros(self):
        """Devuelve la lista de parámetros no vacíos en orden."""
        result = []
        for i in range(1, 11):
            v = getattr(self, f"parametro_{i}")
            if v and v.strip():
                result.append(v.strip())
        return result
