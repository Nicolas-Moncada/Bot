"""
Clinica Odontologica Boutique "Lujo Luminoso"
Script Administrativo: Creacion y Aprovisionamiento de Usuario Administrador
(scripts/crear_admin.py)

Permite registrar un nuevo administrador o elevar un usuario existente al rol ADMIN,
aplicando hashing seguro Argon2id y validacion de contrasenas seguras.

Uso:
  python scripts/crear_admin.py --email admin@lujoluminoso.co --nombre "Director Clinico" --password "ClinicaAdmin#2026!Segura"
  (O simplemente ejecutar sin argumentos para modo interactivo)

Normas estrictas: Cero emojis en codigo y consola.
"""

import argparse
import getpass
import os
import sys

# Asegurar path raiz del proyecto
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.constants import RolStaff
from app.database import ClinicRepository
from app.security import hash_password, validate_password_not_leaked


def main():
    parser = argparse.ArgumentParser(description="Crear usuario Administrador en Lujo Luminoso")
    parser.add_argument("--email", help="Correo electronico del administrador")
    parser.add_argument("--nombre", help="Nombre completo del administrador")
    parser.add_argument("--password", help="Contrasena segura (minimo 10 caracteres)")

    args = parser.parse_args()

    print("=" * 80)
    print("APROVISIONAMIENTO DE USUARIO ADMINISTRADOR - CLINICA LUJO LUMINOSO")
    print("=" * 80)

    # 1. Obtener email
    email = args.email
    if not email:
        email = input("Ingrese el correo electronico del administrador: ").strip()

    email = email.lower().strip()
    if not email or "@" not in email:
        print("ERROR: Correo electronico invalido.")
        sys.exit(1)

    # 2. Obtener nombre
    nombre = args.nombre
    if not nombre:
        nombre = input("Ingrese el nombre completo del administrador: ").strip()

    if not nombre:
        nombre = "Administrador Principal"

    # 3. Obtener contrasena
    password = args.password
    if not password:
        password = getpass.getpass("Ingrese una contrasena segura (minimo 10 caracteres): ")

    if len(password) < 10:
        print("ERROR: La contrasena debe contener al menos 10 caracteres.")
        sys.exit(1)

    try:
        validate_password_not_leaked(password)
    except Exception as exc:
        print(f"ERROR DE SEGURIDAD: {exc}")
        sys.exit(1)

    # 4. Generar hash Argon2id
    print("\nGenerando hash criptografico Argon2id...")
    hashed = hash_password(password)
    print(f"Hash generado exitosamente: {hashed[:30]}...")

    # 5. Generar sentencia SQL lista para copiar y pegar en Supabase SQL Editor
    sql_statement = f"""
-- Sentencia SQL para ejecutar en el SQL Editor de Supabase:
INSERT INTO public.usuarios_staff (email, password_hash, nombre, rol, activo)
VALUES ('{email}', '{hashed}', '{nombre}', 'admin', true)
ON CONFLICT (email) DO UPDATE 
SET rol = 'admin', activo = true, password_hash = EXCLUDED.password_hash, nombre = EXCLUDED.nombre;
""".strip()

    # 6. Intentar registrar en base de datos si esta disponible
    print("\nIntentando conectar con la base de datos Supabase...")
    try:
        repo = ClinicRepository()
        existente = repo.get_staff_by_email(email)
        if existente:
            # Actualizar a rol admin y nueva contrasena
            repo.client.table("usuarios_staff").update({
                "password_hash": hashed,
                "nombre": nombre,
                "rol": RolStaff.ADMIN.value,
                "activo": True
            }).eq("email", email).execute()
            print(f"[OK] Usuario '{email}' actualizado exitosamente como ADMIN en Supabase.")
        else:
            # Crear nuevo registro
            repo.create_staff(
                email=email,
                password_hash=hashed,
                nombre=nombre,
                rol=RolStaff.ADMIN
            )
            print(f"[OK] Usuario '{email}' creado exitosamente con rol ADMIN en Supabase.")
    except Exception as exc:
        print(f"[AVISO] No se pudo conectar directamente con Supabase: {exc}")
        print("\nPuede registrar o actualizar el administrador directamente en el SQL Editor")
        print("de su Dashboard de Supabase ejecutando la siguiente consulta:")
        print("-" * 80)
        print(sql_statement)
        print("-" * 80)

    print("\nCredenciales del Administrador configuradas:")
    print(f"  Correo: {email}")
    print(f"  Nombre: {nombre}")
    print(f"  Rol:    {RolStaff.ADMIN.value}")
    print("\nPara iniciar sesion:")
    print("  1. Inicie el servidor con: uvicorn app.main:app --reload")
    print("  2. Ingrese a http://127.0.0.1:8000/")
    print("  3. Haga clic en 'Acceso Clinico' (arriba a la derecha)")
    print("  4. Ingrese con el correo y contrasena configurados.")
    print("=" * 80)


if __name__ == "__main__":
    main()
