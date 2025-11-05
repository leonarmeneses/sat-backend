import sqlite3
import hashlib
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'sat_users.db')

def init_db():
    """Inicializa la base de datos con las tablas necesarias"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Tabla de usuarios
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            telefono TEXT,
            password_hash TEXT NOT NULL,
            fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabla de datos fiscales
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS datos_fiscales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            rfc TEXT NOT NULL,
            certificado_path TEXT NOT NULL,
            llave_path TEXT NOT NULL,
            password_encrypted TEXT NOT NULL,
            fecha_subida TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (usuario_id) REFERENCES usuarios (id),
            UNIQUE(usuario_id, rfc)
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ Base de datos inicializada")

def hash_password(password):
    """Genera un hash SHA-256 de la contraseña"""
    return hashlib.sha256(password.encode()).hexdigest()

def registrar_usuario(nombre, email, telefono, password):
    """Registra un nuevo usuario"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        password_hash = hash_password(password)
        
        cursor.execute('''
            INSERT INTO usuarios (nombre, email, telefono, password_hash)
            VALUES (?, ?, ?, ?)
        ''', (nombre, email, telefono, password_hash))
        
        conn.commit()
        usuario_id = cursor.lastrowid
        conn.close()
        
        return {'success': True, 'usuario_id': usuario_id}
    except sqlite3.IntegrityError:
        return {'success': False, 'message': 'El email ya está registrado'}
    except Exception as e:
        return {'success': False, 'message': str(e)}

def validar_login(email, password):
    """Valida las credenciales de login"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        password_hash = hash_password(password)
        
        cursor.execute('''
            SELECT id, nombre, email, telefono
            FROM usuarios
            WHERE email = ? AND password_hash = ?
        ''', (email, password_hash))
        
        usuario = cursor.fetchone()
        conn.close()
        
        if usuario:
            return {
                'success': True,
                'usuario': {
                    'id': usuario[0],
                    'nombre': usuario[1],
                    'email': usuario[2],
                    'telefono': usuario[3]
                }
            }
        else:
            return {'success': False, 'message': 'Email o contraseña incorrectos'}
    except Exception as e:
        return {'success': False, 'message': str(e)}

def guardar_datos_fiscales(usuario_id, rfc, certificado_data, llave_data, password_fiscal):
    """Guarda los datos fiscales del usuario"""
    try:
        # Crear directorio para certificados si no existe
        certs_dir = os.path.join(os.path.dirname(__file__), 'certificados_usuarios', str(usuario_id))
        os.makedirs(certs_dir, exist_ok=True)
        
        # Guardar archivos de certificado y llave
        cert_path = os.path.join(certs_dir, f'{rfc}.cer')
        key_path = os.path.join(certs_dir, f'{rfc}.key')
        
        with open(cert_path, 'wb') as f:
            f.write(certificado_data)
        
        with open(key_path, 'wb') as f:
            f.write(llave_data)
        
        # Guardar la contraseña en texto plano (en producción usar cifrado AES)
        # Por ahora es más importante la funcionalidad
        # TODO: Implementar cifrado AES con una clave maestra
        password_encrypted = password_fiscal  # Temporal: sin cifrar
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Actualizar o insertar datos fiscales
        cursor.execute('''
            INSERT INTO datos_fiscales (usuario_id, rfc, certificado_path, llave_path, password_encrypted)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(usuario_id, rfc) DO UPDATE SET
                certificado_path = excluded.certificado_path,
                llave_path = excluded.llave_path,
                password_encrypted = excluded.password_encrypted,
                fecha_subida = CURRENT_TIMESTAMP
        ''', (usuario_id, rfc, cert_path, key_path, password_encrypted))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Datos fiscales guardados en DB para usuario {usuario_id}, RFC {rfc}")
        print(f"   - Cert: {cert_path}")
        print(f"   - Key: {key_path}")
        
        return {'success': True, 'message': 'Datos fiscales guardados correctamente'}
    except Exception as e:
        return {'success': False, 'message': str(e)}

def obtener_datos_fiscales(usuario_id, rfc=None):
    """Obtiene los datos fiscales de un usuario"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        if rfc:
            cursor.execute('''
                SELECT rfc, certificado_path, llave_path, password_encrypted
                FROM datos_fiscales
                WHERE usuario_id = ? AND rfc = ?
            ''', (usuario_id, rfc))
        else:
            cursor.execute('''
                SELECT rfc, certificado_path, llave_path, password_encrypted
                FROM datos_fiscales
                WHERE usuario_id = ?
                ORDER BY fecha_subida DESC
            ''', (usuario_id,))
        
        resultados = cursor.fetchall()
        conn.close()
        
        if resultados:
            datos = []
            for row in resultados:
                datos.append({
                    'rfc': row[0],
                    'certificado_path': row[1],
                    'llave_path': row[2],
                    'password_encrypted': row[3]
                })
            return {'success': True, 'datos': datos if not rfc else datos[0]}
        else:
            return {'success': False, 'message': 'No se encontraron datos fiscales'}
    except Exception as e:
        return {'success': False, 'message': str(e)}

# Inicializar la base de datos al importar el módulo
if __name__ == '__main__':
    init_db()
