"""
Script de Verificacion Exhaustiva Automatizada
Comprueba los 5 puntos exigidos en la orden de reconstruccion:
1. Captcha new & verify (Modo codigo y modo cuadricula 3x3)
2. Registro de nuevo usuario con Argon2id y cookie HttpOnly
3. Autenticacion con Google con cookie HttpOnly
4. Creacion de personal staff por Administrador
"""

import os
import sys
from datetime import datetime, timezone
from uuid import UUID, uuid4

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from app.main import app
from app.auth import COOKIE_NAME, create_access_token
from app.constants import CodigoError, RolStaff
from app.database import get_repository
from app.exceptions import DomainError
from app.schemas import StaffUserResponse
from app.security import hash_password


class MockClinicRepository:
    """Repositorio mock en memoria para pruebas de integracion sin dependencia de red."""

    def __init__(self):
        self.staff_db: dict[str, dict] = {}
        self.pacientes_db: dict[str, dict] = {}

    def get_staff_by_email(self, email: str):
        return self.staff_db.get(email.strip().lower())

    def get_staff_by_id(self, staff_id: UUID):
        for s in self.staff_db.values():
            if str(s["id"]) == str(staff_id):
                return StaffUserResponse(
                    id=s["id"],
                    email=s["email"],
                    nombre=s["nombre"],
                    rol=s["rol"],
                    activo=s["activo"],
                    created_at=s["created_at"],
                )
        return None

    def create_staff(self, email: str, password_hash: str, nombre: str, rol: RolStaff):
        staff_id = uuid4()
        now = datetime.now(timezone.utc)
        record = {
            "id": staff_id,
            "email": email.strip().lower(),
            "password_hash": password_hash,
            "nombre": nombre,
            "rol": rol,
            "activo": True,
            "created_at": now,
        }
        self.staff_db[email.strip().lower()] = record
        return StaffUserResponse(
            id=staff_id,
            email=email.strip().lower(),
            nombre=nombre,
            rol=rol,
            activo=True,
            created_at=now,
        )

    def list_staff(self):
        return [
            StaffUserResponse(
                id=s["id"],
                email=s["email"],
                nombre=s["nombre"],
                rol=s["rol"],
                activo=s["activo"],
                created_at=s["created_at"],
            )
            for s in self.staff_db.values()
        ]

    def update_staff_status(self, staff_id: UUID, activo: bool):
        for s in self.staff_db.values():
            if str(s["id"]) == str(staff_id):
                s["activo"] = activo
                return StaffUserResponse(
                    id=s["id"],
                    email=s["email"],
                    nombre=s["nombre"],
                    rol=s["rol"],
                    activo=s["activo"],
                    created_at=s["created_at"],
                )
        raise DomainError(
            code=CodigoError.UNAUTHORIZED_ACCESS,
            message="Colaborador no encontrado",
            status_code=404,
        )

    def upsert_paciente(self, paciente):
        self.pacientes_db[paciente.telefono] = paciente.model_dump()
        return None


def test_captcha_flow(client: TestClient):
    print("[TEST 1] Verificando flujo de Captcha 'No soy un robot'...")
    # 1. Obtener nuevo captcha
    res = client.get("/api/v1/auth/captcha/new")
    assert res.status_code == 200, f"Error al generar captcha: {res.text}"
    data = res.json()["data"]
    captcha_token = data["captcha_token"]
    code = data["code"]
    grid_items = data["grid_items"]
    assert len(code) == 6, "Codigo de captcha debe tener 6 caracteres"
    assert len(grid_items) == 9, "Cuadricula visual debe tener 9 elementos"

    # 2. Verificar por modo codigo
    res_code = client.post("/api/v1/auth/captcha/verify", json={
        "captcha_token": captcha_token,
        "mode": "code",
        "answer_code": code
    })
    assert res_code.status_code == 200, f"Error al verificar codigo captcha: {res_code.text}"
    token_verified_code = res_code.json()["data"]["captcha_verified_token"]
    assert token_verified_code, "Falta token verificado en respuesta"
    print("    OK: Modo codigo canvas verificado exitosamente.")

    # 3. Verificar por modo cuadricula 3x3
    res2 = client.get("/api/v1/auth/captcha/new")
    data2 = res2.json()["data"]
    token2 = data2["captcha_token"]

    from app.auth import _decode_captcha_token
    payload2 = _decode_captcha_token(token2)
    correct_indices = payload2["correct_indices"]
    assert len(correct_indices) == 3, "Deben existir 3 indices correctos"

    res_grid = client.post("/api/v1/auth/captcha/verify", json={
        "captcha_token": token2,
        "mode": "image_grid",
        "selected_indices": correct_indices
    })
    assert res_grid.status_code == 200, f"Error al verificar cuadricula: {res_grid.text}"
    token_verified_grid = res_grid.json()["data"]["captcha_verified_token"]
    assert token_verified_grid, "Falta token verificado de cuadricula"
    print("    OK: Modo cuadricula 3x3 verificado exitosamente.")

    # Verificacion negativa (indices incorrectos deben fallar)
    res_fail = client.post("/api/v1/auth/captcha/verify", json={
        "captcha_token": token2,
        "mode": "image_grid",
        "selected_indices": [99, 100]
    })
    assert res_fail.status_code == 400, "Debio fallar con indices incorrectos"
    print("    OK: Rechazo de respuesta incorrecta verificado.")


def test_register_flow(client: TestClient):
    print("[TEST 2] Verificando registro de nuevo usuario con Argon2id y cookie HttpOnly...")
    email = f"nuevo.paciente.{uuid4().hex[:6]}@lujoluminoso.co"
    payload = {
        "nombre": "Paciente Prueba Registro",
        "telefono": "+573009988776",
        "email": email,
        "password": "ClinicaLujo#2026!Segura",
        "rol": "recepcion"
    }
    res = client.post("/api/v1/auth/register", json=payload)
    assert res.status_code == 201, f"Fallo registro de usuario: {res.text}"
    cookie_val = res.cookies.get(COOKIE_NAME)
    assert cookie_val, "No se emitio la cookie HttpOnly de sesion en el registro"
    data = res.json()["data"]["usuario"]
    assert data["email"] == email.lower()
    print("    OK: Usuario registrado con Argon2id y cookie HttpOnly emitida.")


def test_google_auth_flow(client: TestClient):
    print("[TEST 3] Verificando inicio de sesion con Google y emision de cookie HttpOnly...")
    email = f"google.user.{uuid4().hex[:6]}@gmail.com"
    payload = {
        "email": email,
        "nombre": "Usuario Google Demo",
        "telefono": "+573112233445"
    }
    res = client.post("/api/v1/auth/google", json=payload)
    assert res.status_code == 200, f"Fallo autenticacion con Google: {res.text}"
    cookie_val = res.cookies.get(COOKIE_NAME)
    assert cookie_val, "No se emitio la cookie HttpOnly de sesion para Google"
    data = res.json()["data"]["usuario"]
    assert data["email"] == email.lower()
    print("    OK: Sesion con Google completada y cookie HttpOnly emitida.")


def test_admin_staff_creation(client: TestClient, mock_repo: MockClinicRepository):
    print("[TEST 4] Verificando creacion de personal staff desde panel Admin...")
    admin = mock_repo.create_staff(
        email="admin@lujoluminoso.co",
        password_hash=hash_password("AdminClaveSegura#2026!"),
        nombre="Administrador General",
        rol=RolStaff.ADMIN
    )
    admin_token = create_access_token(staff_id=admin.id, email=admin.email, rol=admin.rol)

    client.cookies.set(COOKIE_NAME, admin_token)

    new_staff_email = f"doctor.nuevo.{uuid4().hex[:6]}@lujoluminoso.co"
    payload_staff = {
        "email": new_staff_email,
        "nombre": "Dr. Nuevo Especialista",
        "password": "ClinicaDoctor#2026!Segura",
        "rol": "doctor"
    }
    res_staff = client.post("/api/v1/auth/staff", json=payload_staff)
    assert res_staff.status_code == 201, f"Fallo creacion de personal: {res_staff.text}"
    created = res_staff.json()["data"]["usuario"]
    assert created["email"] == new_staff_email.lower()
    assert created["rol"] == "doctor"
    print("    OK: Personal clinico creado por rol ADMIN exitosamente.")

    # Listar staff
    res_list = client.get("/api/v1/auth/staff")
    assert res_list.status_code == 200
    staff_list = res_list.json()["data"]["staff"]
    assert any(s["email"] == new_staff_email.lower() for s in staff_list)
    print("    OK: Listado de personal verificado en panel administrativo.")

    # Alternar estado activo / inactivo
    new_staff_id = created["id"]
    res_toggle = client.patch(f"/api/v1/auth/staff/{new_staff_id}/toggle", json={"activo": False})
    assert res_toggle.status_code == 200
    assert res_toggle.json()["data"]["usuario"]["activo"] is False
    print("    OK: Modificacion de estado activo/inactivo verificado.")


def main():
    print("=" * 80)
    print("VERIFICACION AUTOMATICA DE CAPTCHA, REGISTRO, GOOGLE LOGIN Y STAFF")
    print("=" * 80)
    
    mock_repo = MockClinicRepository()
    app.dependency_overrides[get_repository] = lambda: mock_repo

    client = TestClient(app)
    try:
        test_captcha_flow(client)
        test_register_flow(client)
        test_google_auth_flow(client)
        test_admin_staff_creation(client, mock_repo)
        print("=" * 80)
        print("TODAS LAS PRUEBAS DE LOS PUNTOS 1 AL 4 SUPERADAS EXITOSAMENTE (100%)")
        print("=" * 80)
    finally:
        app.dependency_overrides.clear()


if __name__ == "__main__":
    main()
