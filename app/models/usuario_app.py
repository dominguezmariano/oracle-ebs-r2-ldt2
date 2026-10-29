from app import db
from datetime import datetime


class UsuarioApp(db.Model):
    __tablename__ = "usuarios_app"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False)
    nombre_completo = db.Column(db.String(200))
    ambiente_id = db.Column(db.Integer, db.ForeignKey("ambientes.id"), nullable=False)
    activo = db.Column(db.Boolean, default=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)

    ambiente = db.relationship("Ambiente", backref="usuarios")

    def __repr__(self):
        return f"<UsuarioApp {self.username}>"
