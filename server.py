from flask import Flask, request, jsonify, session
from flask_cors import CORS
from flask_session import Session
import os
from datetime import datetime, timedelta
from cfdiclient import Autenticacion, SolicitaDescargaEmitidos, SolicitaDescargaRecibidos, VerificaSolicitudDescarga, Fiel
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import base64
import database

app = Flask(__name__)
app.secret_key = 'clave_secreta_super_segura_cambiar_en_produccion'  # Cambiar en producción

# Configuración de sesión con Flask-Session (almacenamiento en archivos)
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = os.path.join(os.path.dirname(__file__), 'flask_session')
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_KEY_PREFIX'] = 'sat_session:'
# Configuración de cookies para producción HTTPS
app.config['SESSION_COOKIE_NAME'] = 'sat_session'
app.config['SESSION_COOKIE_SAMESITE'] = 'None'  # None permite CORS cross-site
app.config['SESSION_COOKIE_SECURE'] = True  # True para HTTPS en producción
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_DOMAIN'] = None
app.config['SESSION_COOKIE_PATH'] = '/'

# Inicializar Flask-Session
Session(app)

# Configuración CORS para producción y desarrollo
CORS(app, 
     supports_credentials=True, 
     origins=[
         'http://localhost', 
         'http://localhost:80', 
         'http://127.0.0.1', 
         'http://127.0.0.1:80',
         'https://meneseswebs.com',
         'https://www.meneseswebs.com',
         'https://generador.meneseswebs.com',
         'https://sat-backend-jbmx.onrender.com'
     ],
     allow_headers=['Content-Type', 'Authorization'],
     methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
     expose_headers=['Set-Cookie'])

# Inicializar base de datos
database.init_db()

class SATClient:
    def __init__(self, rfc, cert_path, key_path, key_password):
        self.rfc = rfc
        self.cert_path = cert_path
        self.key_path = key_path
        self.key_password = key_password
        self.token = None
        self.fiel = None
    
    def inicializar_fiel(self):
        """Inicializa la FIEL usando cfdiclient"""
        try:
            print(f"🔐 Inicializando FIEL para RFC: {self.rfc}")
            
            # Leer certificado
            with open(self.cert_path, 'rb') as f:
                cer_der = f.read()
            
            # Leer llave
            with open(self.key_path, 'rb') as f:
                key_der = f.read()
            
            print(f"✅ Archivos leídos correctamente")
            
            # Convertir la llave de formato DER encriptado a PEM
            # (cfdiclient usa pycrypto que necesita formato específico)
            try:
                print(f"🔄 Convirtiendo llave privada...")
                private_key = serialization.load_der_private_key(
                    key_der,
                    password=self.key_password.encode() if self.key_password else None,
                    backend=default_backend()
                )
                
                # Convertir a PEM sin encripción (cfdiclient lo manejará)
                key_pem = private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption()
                )
                
                print(f"✅ Llave convertida a PEM")
                
            except Exception as e:
                print(f"❌ Error al convertir llave: {e}")
                return False
            
            # Crear objeto Fiel con certificado DER y llave PEM
            self.fiel = Fiel(cer_der, key_pem, b'')  # Sin password porque ya desencriptamos
            print(f"✅ FIEL inicializada correctamente")
            return True
            
        except Exception as e:
            print(f"❌ Error al inicializar FIEL: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def autenticar(self):
        """Autentica con el SAT usando cfdiclient"""
        try:
            if not self.fiel:
                if not self.inicializar_fiel():
                    return False
            
            print(f"📤 Solicitando token de autenticación...")
            
            # Usar cfdiclient para autenticar
            auth = Autenticacion(self.fiel)
            self.token = auth.obtener_token()
            
            print(f"✅ Token obtenido: {self.token[:50] if self.token else 'None'}...")
            return True if self.token else False
            
        except Exception as e:
            print(f"❌ Error en autenticación: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def solicitar_descarga(self, fecha_inicial, fecha_final, tipo_solicitud='CFDI', estado_comprobante=None):
        """
        Solicita descarga de facturas usando cfdiclient
        tipo_solicitud: 'emitidas' o 'recibidas'
        estado_comprobante: None (todos), 0 (canceladas), 1 (vigentes)
        """
        try:
            if not self.token:
                if not self.autenticar():
                    return None
            
            print(f"📥 Solicitando descarga de facturas {tipo_solicitud}...")
            print(f"📅 Desde: {fecha_inicial} hasta: {fecha_final}")
            print(f"🔑 RFC: {self.rfc}")
            if estado_comprobante is not None:
                estado_texto = "Vigentes" if estado_comprobante == 1 else "Canceladas"
                print(f"📋 Estado comprobante: {estado_texto} ({estado_comprobante})")
            else:
                print(f"📋 Estado comprobante: Todos")
            
            # Usar la clase correcta según el tipo
            if tipo_solicitud == 'emitidas':
                descarga = SolicitaDescargaEmitidos(self.fiel)
                print(f"📤 Solicitando EMITIDAS con rfc_emisor={self.rfc}")
                
                # Construir parámetros según el estado
                params = {
                    'token': self.token,
                    'rfc_solicitante': self.rfc,
                    'fecha_inicial': fecha_inicial,
                    'fecha_final': fecha_final,
                    'rfc_emisor': self.rfc
                }
                
                # Agregar estado_comprobante solo si se especificó
                # IMPORTANTE: cfdiclient requiere que sea string, no int
                if estado_comprobante is not None:
                    params['estado_comprobante'] = str(estado_comprobante)
                    print(f"🔧 Agregando filtro estado_comprobante = '{estado_comprobante}' (como string)")
                
                print(f"📦 Parámetros de solicitud: {params}")
                solicitud = descarga.solicitar_descarga(**params)
            else:  # recibidas
                descarga = SolicitaDescargaRecibidos(self.fiel)
                print(f"📥 Solicitando RECIBIDAS con rfc_receptor={self.rfc}")
                
                # Construir parámetros según el estado
                params = {
                    'token': self.token,
                    'rfc_solicitante': self.rfc,
                    'fecha_inicial': fecha_inicial,
                    'fecha_final': fecha_final,
                    'rfc_receptor': self.rfc
                }
                
                # Agregar estado_comprobante solo si se especificó
                # IMPORTANTE: cfdiclient requiere que sea string, no int
                if estado_comprobante is not None:
                    params['estado_comprobante'] = str(estado_comprobante)
                    print(f"🔧 Agregando filtro estado_comprobante = '{estado_comprobante}' (como string)")
                
                print(f"📦 Parámetros de solicitud: {params}")
                solicitud = descarga.solicitar_descarga(**params)
            
            print(f"✅ Solicitud creada: {solicitud}")
            return solicitud
            
        except Exception as e:
            print(f"❌ Error al solicitar descarga: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def verificar_solicitud(self, id_solicitud):
        """Verifica el estado de una solicitud de descarga"""
        try:
            if not self.token:
                if not self.autenticar():
                    return None
            
            print(f"🔍 Verificando solicitud: {id_solicitud}")
            
            verificacion = VerificaSolicitudDescarga(self.fiel)
            resultado = verificacion.verificar_descarga(
                self.token,
                self.rfc,
                id_solicitud
            )
            
            print(f"✅ Verificación: {resultado}")
            return resultado
            
        except Exception as e:
            print(f"❌ Error al verificar solicitud: {e}")
            import traceback
            traceback.print_exc()
            return None

# Diccionario global para almacenar clientes SAT por RFC
sat_clients = {}

@app.route('/api/consultar-facturas', methods=['POST'])
def consultar_facturas():
    """Endpoint para consultar facturas del SAT"""
    try:
        print(f"📨 Recibiendo solicitud de consultar facturas...")
        data = request.json
        print(f"Data recibida: {data}")
        
        rfc = data.get('rfc')
        tipo_consulta = data.get('tipo')  # 'emitidas' o 'recibidas'
        fecha_inicial = data.get('fechaInicial')
        fecha_final = data.get('fechaFinal')
        usar_datos_guardados = data.get('usarDatosGuardados', False)
        estado_comprobante = data.get('estadoComprobante')  # None, 0 (canceladas), o 1 (vigentes)
        
        print(f"RFC: {rfc}, Tipo: {tipo_consulta}, Fechas: {fecha_inicial} - {fecha_final}")
        print(f"Usar datos guardados: {usar_datos_guardados}, Estado comprobante: {estado_comprobante}")
        
        if not all([rfc, tipo_consulta, fecha_inicial, fecha_final]):
            missing = []
            if not rfc: missing.append('RFC')
            if not tipo_consulta: missing.append('tipo')
            if not fecha_inicial: missing.append('fecha inicial')
            if not fecha_final: missing.append('fecha final')
            
            error_msg = f'Faltan datos: {", ".join(missing)}'
            print(f"❌ {error_msg}")
            
            return jsonify({
                'success': False,
                'message': error_msg
            }), 400
        
        # Si usamos datos guardados, cargar desde la base de datos
        if usar_datos_guardados and 'usuario_id' in session:
            print(f"🔑 Cargando datos fiscales guardados para usuario {session['usuario_id']}")
            usuario_id = session['usuario_id']
            resultado = database.obtener_datos_fiscales(usuario_id)
            
            print(f"🔑 Resultado de obtener_datos_fiscales: {resultado}")
            
            if not resultado['success']:
                return jsonify({
                    'success': False,
                    'message': 'No se encontraron datos fiscales guardados'
                }), 400
            
            datos_fiscales = resultado['datos']
            print(f"🔑 Datos fiscales encontrados: {len(datos_fiscales)} RFCs")
            
            # Buscar los datos del RFC especificado
            datos_rfc = None
            for datos in datos_fiscales:
                print(f"🔍 Comparando: {datos['rfc']} con {rfc}")
                if datos['rfc'] == rfc:
                    datos_rfc = datos
                    break
            
            if not datos_rfc:
                return jsonify({
                    'success': False,
                    'message': f'No se encontraron datos guardados para el RFC {rfc}'
                }), 400
            
            # Leer los archivos de certificados guardados
            cert_path = datos_rfc['certificado_path']
            key_path = datos_rfc['llave_path']
            password_fiscal = datos_rfc['password_encrypted']  # Ahora es la contraseña en texto plano
            
            print(f"✅ Certificados guardados encontrados:")
            print(f"   - Certificado: {cert_path}")
            print(f"   - Llave: {key_path}")
            print(f"   - Password: {'*' * len(password_fiscal)}")
            
            # Verificar que los archivos existan
            if not os.path.exists(cert_path) or not os.path.exists(key_path):
                return jsonify({
                    'success': False,
                    'message': 'Los archivos de certificados no existen. Vuelve a subirlos en tu perfil.'
                }), 400
            
            # Crear o recuperar cliente
            if rfc not in sat_clients:
                print(f"🔧 Inicializando nuevo cliente SAT con datos guardados")
                client = SATClient(rfc, cert_path, key_path, password_fiscal)
                if not client.inicializar_fiel():
                    return jsonify({
                        'success': False,
                        'message': 'Error al inicializar FIEL con certificados guardados. Verifica que la contraseña sea correcta.'
                    }), 400
                sat_clients[rfc] = client
                print(f"✅ Cliente SAT inicializado correctamente")
            else:
                print(f"♻️ Reutilizando cliente SAT existente")
                client = sat_clients[rfc]
        else:
            print(f"📂 Usando certificados subidos manualmente")
            # Verificar que existan los certificados subidos temporalmente
            cert_path = f'certificados/{rfc}.cer'
            key_path = f'certificados/{rfc}.key'
            
            if not os.path.exists(cert_path) or not os.path.exists(key_path):
                return jsonify({
                    'success': False,
                    'message': 'Primero debes subir los certificados'
                }), 400
            
            # Obtener o crear cliente SAT
            if rfc not in sat_clients:
                return jsonify({
                    'success': False,
                    'message': 'Cliente no inicializado. Sube los certificados primero.'
                }), 400
            
            client = sat_clients[rfc]
        
        # Convertir fechas
        fecha_ini = datetime.strptime(fecha_inicial, '%Y-%m-%d')
        fecha_fin = datetime.strptime(fecha_final, '%Y-%m-%d')
        
        # Solicitar descarga con estado del comprobante
        solicitud = client.solicitar_descarga(
            fecha_ini,
            fecha_fin,
            tipo_solicitud=tipo_consulta,
            estado_comprobante=estado_comprobante
        )
        
        if not solicitud:
            return jsonify({
                'success': False,
                'message': 'Error al solicitar descarga'
            }), 500
        
        # Analizar el código de estatus
        cod_estatus = solicitud.get('cod_estatus', '')
        id_solicitud = solicitud.get('id_solicitud')
        mensaje = solicitud.get('mensaje', '')
        
        # Códigos de estatus del SAT:
        # 5000 = Solicitud aceptada
        # 5004 = No se encontraron CFDIs
        # 301 = Error en la solicitud
        # 305 = Solicitud duplicada
        # 404 = Error no controlado (puede ser que no hay datos)
        
        if cod_estatus == '5000':
            # Solicitud exitosa, verificar estado
            if id_solicitud:
                verificacion = client.verificar_solicitud(id_solicitud)
                return jsonify({
                    'success': True,
                    'solicitud': solicitud,
                    'verificacion': verificacion,
                    'id_solicitud': id_solicitud
                })
            else:
                return jsonify({
                    'success': True,
                    'solicitud': solicitud,
                    'message': 'Solicitud aceptada pero sin ID',
                    'id_solicitud': None
                })
        elif cod_estatus == '5004':
            return jsonify({
                'success': True,
                'message': 'No se encontraron facturas para el período especificado',
                'solicitud': solicitud,
                'id_solicitud': None
            })
        elif cod_estatus == '404':
            # Error no controlado del SAT - puede significar que no hay datos
            return jsonify({
                'success': True,
                'message': 'No se encontraron facturas para el período especificado (404)',
                'solicitud': solicitud,
                'id_solicitud': id_solicitud
            })
        elif cod_estatus == '305':
            # Solicitud duplicada - intentar verificar con el ID previo
            if id_solicitud:
                verificacion = client.verificar_solicitud(id_solicitud)
                return jsonify({
                    'success': True,
                    'message': 'Solicitud duplicada encontrada',
                    'solicitud': solicitud,
                    'verificacion': verificacion,
                    'id_solicitud': id_solicitud
                })
            else:
                return jsonify({
                    'success': False,
                    'message': f'Solicitud duplicada: {mensaje}',
                    'solicitud': solicitud
                })
        elif cod_estatus == '301':
            # Error 301 - generalmente significa que no hay facturas o hay problemas con la consulta
            tipo_texto = 'emitidas' if tipo_consulta == 'emitidas' else 'recibidas'
            
            # Verificar si el error es por incluir canceladas
            if 'cancelado' in mensaje.lower():
                return jsonify({
                    'success': False,
                    'sin_facturas': False,
                    'message': 'Error: El SAT no permite descargar facturas canceladas junto con vigentes. Por favor, selecciona solo "Vigentes" o solo "Canceladas".',
                    'detalle': mensaje,
                    'solicitud': solicitud,
                    'cod_estatus': cod_estatus
                }), 400
            
            return jsonify({
                'success': True,
                'sin_facturas': True,
                'message': f'No tienes facturas {tipo_texto} en estas fechas',
                'detalle': 'No se encontraron documentos fiscales en el período especificado',
                'solicitud': solicitud,
                'cod_estatus': cod_estatus
            })
        else:
            # Otros códigos de error - también tratarlos como "sin facturas" si no es crítico
            print(f"⚠️ Código de estado no manejado: {cod_estatus}")
            print(f"⚠️ Mensaje: {mensaje}")
            print(f"⚠️ ID Solicitud: {id_solicitud}")
            
            # Si el mensaje indica que no hay datos, tratarlo como sin facturas
            if 'no se encontr' in mensaje.lower() or 'no existe' in mensaje.lower() or 'no hay' in mensaje.lower():
                tipo_texto = 'emitidas' if tipo_consulta == 'emitidas' else 'recibidas'
                return jsonify({
                    'success': True,
                    'sin_facturas': True,
                    'message': f'No tienes facturas {tipo_texto} en estas fechas',
                    'detalle': mensaje,
                    'solicitud': solicitud,
                    'cod_estatus': cod_estatus
                })
            
            # Si es un error real, devolverlo como error
            return jsonify({
                'success': False,
                'message': mensaje or 'Error al procesar la solicitud',
                'solicitud': solicitud,
                'cod_estatus': cod_estatus
            }), 400
        
    except Exception as e:
        print(f"❌ Error en consultar_facturas: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'Error del servidor: {str(e)}'
        }), 500

@app.route('/api/subir-certificados', methods=['POST'])
def subir_certificados():
    """Endpoint para subir certificados del SAT"""
    try:
        print(f"📨 Recibiendo solicitud de subir certificados...")
        print(f"Form data: {request.form}")
        print(f"Files: {request.files}")
        
        rfc = request.form.get('rfc')
        password = request.form.get('password')
        cert_file = request.files.get('certificado')
        key_file = request.files.get('llave')
        
        print(f"RFC: {rfc}")
        print(f"Password: {'***' if password else 'None'}")
        print(f"Certificado: {cert_file.filename if cert_file else 'None'}")
        print(f"Llave: {key_file.filename if key_file else 'None'}")
        
        if not all([rfc, password, cert_file, key_file]):
            missing = []
            if not rfc: missing.append('RFC')
            if not password: missing.append('contraseña')
            if not cert_file: missing.append('certificado')
            if not key_file: missing.append('llave')
            
            error_msg = f'Faltan: {", ".join(missing)}'
            print(f"❌ {error_msg}")
            
            return jsonify({
                'success': False,
                'message': error_msg
            }), 400
        
        # Crear directorio si no existe
        os.makedirs('certificados', exist_ok=True)
        
        # Guardar archivos
        cert_path = f'certificados/{rfc}.cer'
        key_path = f'certificados/{rfc}.key'
        
        cert_file.save(cert_path)
        key_file.save(key_path)
        
        print(f"📁 Certificados guardados para RFC: {rfc}")
        
        # Crear cliente SAT
        client = SATClient(rfc, cert_path, key_path, password)
        
        # Inicializar FIEL para verificar que los certificados son válidos
        if not client.inicializar_fiel():
            # Eliminar archivos si falló la inicialización
            os.remove(cert_path)
            os.remove(key_path)
            return jsonify({
                'success': False,
                'message': 'Certificados o contraseña inválidos'
            }), 400
        
        # Guardar cliente en memoria
        sat_clients[rfc] = client
        
        return jsonify({
            'success': True,
            'message': 'Certificados subidos correctamente'
        })
        
    except Exception as e:
        print(f"❌ Error al subir certificados: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'Error al procesar certificados: {str(e)}'
        }), 500

# ============================================================================
# ENDPOINTS DE AUTENTICACIÓN
# ============================================================================

@app.route('/api/register', methods=['POST'])
def register():
    """Registrar nuevo usuario"""
    try:
        print("📝 Recibiendo solicitud de registro...")
        data = request.get_json()
        print(f"Datos recibidos: {data}")
        
        nombre = data.get('nombre')
        email = data.get('email')
        telefono = data.get('telefono')
        password = data.get('password')
        
        print(f"Nombre: {nombre}, Email: {email}, Telefono: {telefono}")
        
        if not all([nombre, email, password]):
            print("❌ Faltan datos requeridos")
            return jsonify({
                'success': False,
                'message': 'Faltan datos requeridos'
            }), 400
        
        print(f"🔐 Intentando registrar usuario: {email}")
        resultado = database.registrar_usuario(nombre, email, telefono, password)
        
        if resultado['success']:
            usuario_id = resultado['usuario_id']
            # Limpiar sesión anterior
            session.clear()
            # Crear sesión permanente
            session.permanent = True
            session['usuario_id'] = usuario_id
            session['email'] = email
            session['nombre'] = nombre
            session.modified = True  # Forzar guardado de sesión
            
            print(f"✅ Usuario registrado exitosamente: ID {usuario_id}")
            print(f"Session guardada: {dict(session)}")
            
            return jsonify({
                'success': True,
                'message': 'Usuario registrado exitosamente',
                'usuario_id': usuario_id
            })
        else:
            print(f"⚠️ Error en registro: {resultado.get('message', 'Error desconocido')}")
            return jsonify({
                'success': False,
                'message': resultado.get('message', 'Error al registrar usuario')
            }), 400
            
    except Exception as e:
        print(f"❌ Error al registrar usuario: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'Error al registrar: {str(e)}'
        }), 500

@app.route('/api/login', methods=['POST'])
def login():
    """Iniciar sesión"""
    try:
        print("🔑 Recibiendo solicitud de login...")
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')
        
        print(f"Email: {email}")
        
        if not all([email, password]):
            print("❌ Faltan credenciales")
            return jsonify({
                'success': False,
                'message': 'Email y contraseña son requeridos'
            }), 400
        
        resultado = database.validar_login(email, password)
        print(f"Resultado validación: {resultado}")
        
        if resultado.get('success'):
            usuario = resultado['usuario']
            # Limpiar sesión anterior
            session.clear()
            # Crear sesión permanente
            session.permanent = True
            session['usuario_id'] = usuario['id']
            session['email'] = usuario['email']
            session['nombre'] = usuario['nombre']
            session.modified = True  # Forzar guardado de sesión
            
            print(f"✅ Login exitoso para: {email}")
            print(f"Session guardada: {dict(session)}")
            print(f"Session ID: {session.get('_id', 'No ID')}")
            
            return jsonify({
                'success': True,
                'message': 'Inicio de sesión exitoso',
                'usuario': usuario
            })
        else:
            print(f"⚠️ Login fallido para: {email}")
            return jsonify({
                'success': False,
                'message': resultado.get('message', 'Email o contraseña incorrectos')
            }), 401
            
    except Exception as e:
        print(f"❌ Error al iniciar sesión: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'Error al iniciar sesión: {str(e)}'
        }), 500

# Middleware para debuggear cookies y sesión
@app.before_request
def log_request_info():
    print(f"\n{'='*60}")
    print(f"📨 REQUEST: {request.method} {request.path}")
    print(f"Origin: {request.headers.get('Origin', 'No origin')}")
    print(f"Cookies recibidas: {dict(request.cookies)}")
    print(f"Session antes: {dict(session)}")
    print(f"{'='*60}\n")

@app.after_request
def log_response_info(response):
    print(f"\n{'='*60}")
    print(f"📤 RESPONSE: {response.status}")
    print(f"Set-Cookie headers: {response.headers.getlist('Set-Cookie')}")
    print(f"Session después: {dict(session)}")
    print(f"{'='*60}\n")
    return response

@app.route('/api/logout', methods=['POST'])
def logout():
    """Cerrar sesión"""
    session.clear()
    return jsonify({
        'success': True,
        'message': 'Sesión cerrada'
    })

@app.route('/api/session', methods=['GET'])
def check_session():
    """Verificar si hay sesión activa"""
    print(f"🔍 Verificando sesión...")
    print(f"Session data: {dict(session)}")
    print(f"¿Tiene usuario_id?: {'usuario_id' in session}")
    
    if 'usuario_id' in session:
        print(f"✅ Sesión activa para usuario: {session.get('email')}")
        return jsonify({
            'success': True,
            'logged_in': True,
            'usuario_id': session['usuario_id'],
            'email': session['email']
        })
    else:
        print(f"❌ No hay sesión activa")
        return jsonify({
            'success': True,
            'logged_in': False
        })

@app.route('/api/guardar-fiscales', methods=['POST'])
def guardar_fiscales():
    """Guardar datos fiscales del usuario"""
    try:
        # Verificar sesión
        if 'usuario_id' not in session:
            return jsonify({
                'success': False,
                'message': 'Debes iniciar sesión'
            }), 401
        
        usuario_id = session['usuario_id']
        print(f"💾 Guardando datos fiscales para usuario {usuario_id}...")
        
        # Obtener datos del formulario
        rfc = request.form.get('rfc')
        password = request.form.get('password')
        cert_file = request.files.get('certificado')
        key_file = request.files.get('llave')
        
        print(f"💾 RFC: {rfc}")
        print(f"💾 Certificado: {cert_file.filename if cert_file else 'None'}")
        print(f"💾 Llave: {key_file.filename if key_file else 'None'}")
        
        if not all([rfc, password, cert_file, key_file]):
            return jsonify({
                'success': False,
                'message': 'Faltan datos fiscales'
            }), 400
        
        # Validar RFC
        if not rfc or len(rfc) < 12 or len(rfc) > 13:
            return jsonify({
                'success': False,
                'message': 'RFC inválido'
            }), 400
        
        # Leer los datos de los archivos
        cert_data = cert_file.read()
        key_data = key_file.read()
        
        print(f"💾 Datos leídos - Cert: {len(cert_data)} bytes, Key: {len(key_data)} bytes")
        
        # Guardar datos fiscales
        resultado = database.guardar_datos_fiscales(
            usuario_id, 
            rfc, 
            cert_data,  # Pasar los datos binarios, no el objeto file
            key_data,   # Pasar los datos binarios, no el objeto file
            password
        )
        
        print(f"💾 Resultado: {resultado}")
        
        if resultado['success']:
            return jsonify({
                'success': True,
                'message': 'Datos fiscales guardados correctamente'
            })
        else:
            return jsonify({
                'success': False,
                'message': resultado.get('message', 'Error al guardar datos fiscales')
            }), 500
            
    except Exception as e:
        print(f"❌ Error al guardar datos fiscales: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'Error al guardar datos: {str(e)}'
        }), 500

@app.route('/api/obtener-fiscales', methods=['GET'])
def obtener_fiscales():
    """Obtener datos fiscales guardados del usuario"""
    try:
        # Verificar sesión
        if 'usuario_id' not in session:
            return jsonify({
                'success': False,
                'message': 'Debes iniciar sesión'
            }), 401
        
        usuario_id = session['usuario_id']
        print(f"📊 Obteniendo datos fiscales para usuario {usuario_id}...")
        
        resultado = database.obtener_datos_fiscales(usuario_id)
        print(f"📊 Resultado de la consulta: {resultado}")
        
        if resultado['success']:
            # La función devuelve {'success': True, 'datos': [...]}
            datos = resultado.get('datos', [])
            print(f"✅ {len(datos)} RFCs encontrados")
            
            return jsonify({
                'success': True,
                'datos_fiscales': datos
            })
        else:
            print(f"❌ No se encontraron datos fiscales: {resultado.get('message')}")
            return jsonify({
                'success': True,
                'datos_fiscales': []
            })
        
    except Exception as e:
        print(f"❌ Error al obtener datos fiscales: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'Error al obtener datos: {str(e)}'
        }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    debug = os.environ.get('DEBUG', 'True') == 'True'
    print(f"🚀 Servidor SAT iniciado en puerto {port}")
    app.run(debug=debug, host='0.0.0.0', port=port)
