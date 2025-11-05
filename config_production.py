# Configuración para producción en Hostinger
import os

# Modo de producción
DEBUG = False

# Puerto asignado por Hostinger (verificar en cPanel -> Setup Python App)
# Usualmente es un puerto entre 30000-65535
PORT = int(os.environ.get('PORT', 5001))

# Host - debe ser 0.0.0.0 para que sea accesible externamente
HOST = '0.0.0.0'

# Secret key para sesiones (CAMBIAR EN PRODUCCIÓN)
SECRET_KEY = os.environ.get('SECRET_KEY', 'tu-clave-secreta-super-segura-cambiar-en-produccion')

# Configuración de CORS - agregar tu dominio
ALLOWED_ORIGINS = [
    'https://tudominio.com',
    'https://www.tudominio.com',
    'http://localhost',  # Solo para pruebas locales
]

# Base de datos
DB_PATH = os.path.join(os.path.dirname(__file__), 'sat_users.db')

# Directorio de certificados
CERTS_DIR = os.path.join(os.path.dirname(__file__), 'certificados_usuarios')

# Sesiones
SESSION_TYPE = 'filesystem'
SESSION_FILE_DIR = os.path.join(os.path.dirname(__file__), 'flask_session')
SESSION_PERMANENT = True
SESSION_USE_SIGNER = True
PERMANENT_SESSION_LIFETIME = 86400  # 24 horas
