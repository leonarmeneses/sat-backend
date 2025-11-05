from flask import Flask, request, jsonify, session
from flask_cors import CORS
from flask_session import Session
import os
from datetime import datetime, timedelta
from cfdiclient import Autenticacion, SolicitaDescargaEmitidos, SolicitaDescargaRecibidos, VerificaSolicitudDescarga, DescargaMasiva, Fiel
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import base64
import zipfile
import io
import xml.etree.ElementTree as ET
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
                
                # IMPORTANTE: Para facturas EMITIDAS, SIEMPRE enviar estado_comprobante='1' (vigentes)
                # Esto evita ambigüedades con el SAT y asegura respuestas más claras
                # Si el usuario quiere canceladas, debe especificar '0' explícitamente
                estado_final = estado_comprobante if estado_comprobante is not None else 1
                params['estado_comprobante'] = str(estado_final)
                estado_texto = "Vigentes" if estado_final == 1 else "Canceladas" if estado_final == 0 else "Todos"
                print(f"🔧 Agregando filtro estado_comprobante = '{estado_final}' ({estado_texto})")
                
                print(f"📦 Parámetros de solicitud: {params}")
                solicitud = descarga.solicitar_descarga(**params)
            else:  # recibidas
                descarga = SolicitaDescargaRecibidos(self.fiel)
                print(f"📥 Solicitando RECIBIDAS con rfc_receptor={self.rfc}")
                
                # Para facturas recibidas, NO usar filtro de estado_comprobante
                # porque el SAT no permite filtrar facturas canceladas por terceros
                params = {
                    'token': self.token,
                    'rfc_solicitante': self.rfc,
                    'fecha_inicial': fecha_inicial,
                    'fecha_final': fecha_final,
                    'rfc_receptor': self.rfc
                }
                
                # IMPORTANTE: Para facturas recibidas, ignoramos estado_comprobante
                # El SAT devuelve todas las facturas (vigentes y canceladas) automáticamente
                print(f"� Parámetros de solicitud (SIN filtro estado_comprobante para recibidas): {params}")
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
    
    def descargar_paquetes(self, id_solicitud):
        """Descarga los paquetes ZIP de una solicitud"""
        try:
            if not self.token:
                if not self.autenticar():
                    print("❌ No se pudo autenticar para descargar paquetes")
                    return None
            
            print(f"📦 Descargando paquetes para solicitud: {id_solicitud}")
            
            descarga = DescargaMasiva(self.fiel)
            
            # El método correcto en cfdiclient es 'descargar', no 'descargar_paquetes'
            try:
                # Obtener la lista de paquetes de la verificación
                verificacion = self.verificar_solicitud(id_solicitud)
                if not verificacion or 'paquetes' not in verificacion:
                    print("⚠️ No hay paquetes disponibles para descargar")
                    return []
                
                paquetes_ids = verificacion['paquetes']
                print(f"📦 Paquetes encontrados: {len(paquetes_ids)}")
                
                paquetes_descargados = []
                for paquete_id in paquetes_ids:
                    try:
                        print(f"⬇️ Descargando paquete: {paquete_id}")
                        # El método correcto es 'descargar_paquete' (singular) según cfdiclient
                        resultado = descarga.descargar_paquete(
                            self.token,
                            self.rfc,
                            paquete_id
                        )
                        
                        if resultado and 'paquete' in resultado:
                            # El paquete viene en base64, necesitamos decodificarlo
                            import base64
                            paquete_b64 = resultado['paquete']
                            paquete_bytes = base64.b64decode(paquete_b64)
                            paquetes_descargados.append(paquete_bytes)
                            print(f"✅ Paquete {paquete_id} descargado: {len(paquete_bytes)} bytes")
                        else:
                            print(f"⚠️ Paquete {paquete_id} sin contenido")
                    except Exception as pe:
                        print(f"❌ Error descargando paquete {paquete_id}: {pe}")
                        continue
                
                print(f"✅ Total de paquetes descargados: {len(paquetes_descargados)}")
                return paquetes_descargados
                    
            except AttributeError as ae:
                print(f"⚠️ Error de atributo en descarga: {ae}")
                import traceback
                traceback.print_exc()
                return []
            except Exception as de:
                print(f"❌ Error en descarga de paquetes: {de}")
                import traceback
                traceback.print_exc()
                return []
            
        except Exception as e:
            print(f"❌ Error general al descargar paquetes: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def parsear_facturas_de_zip(self, zip_data):
        """Extrae y parsea las facturas de un archivo ZIP"""
        facturas = []
        try:
            # Abrir el ZIP desde bytes
            with zipfile.ZipFile(io.BytesIO(zip_data)) as zip_file:
                # Iterar sobre cada archivo XML en el ZIP
                for filename in zip_file.namelist():
                    if filename.endswith('.xml'):
                        try:
                            xml_content = zip_file.read(filename)
                            factura = self.parsear_xml_factura(xml_content)
                            if factura:
                                facturas.append(factura)
                        except Exception as e:
                            print(f"⚠️ Error al parsear {filename}: {e}")
                            continue
        except Exception as e:
            print(f"❌ Error al abrir ZIP: {e}")
        
        return facturas
    
    def parsear_xml_factura(self, xml_content):
        """Parsea un XML de factura y extrae la información principal"""
        try:
            # Parsear el XML
            root = ET.fromstring(xml_content)
            
            # Namespaces del SAT
            ns = {
                'cfdi': 'http://www.sat.gob.mx/cfd/4',
                'cfdi3': 'http://www.sat.gob.mx/cfd/3',
                'tfd': 'http://www.sat.gob.mx/TimbreFiscalDigital'
            }
            
            # Intentar con namespace 4.0 primero, luego 3.3
            comprobante = root
            
            # Extraer datos del comprobante
            fecha = comprobante.get('Fecha', '')
            folio = comprobante.get('Folio', 'N/A')
            serie = comprobante.get('Serie', '')
            total = comprobante.get('Total', '0')
            subtotal = comprobante.get('SubTotal', '0')
            moneda = comprobante.get('Moneda', 'MXN')
            tipo_comprobante = comprobante.get('TipoDeComprobante', 'I')
            
            # Emisor
            emisor = comprobante.find('cfdi:Emisor', ns) or comprobante.find('cfdi3:Emisor', ns)
            rfc_emisor = emisor.get('Rfc', '') if emisor is not None else ''
            nombre_emisor = emisor.get('Nombre', '') if emisor is not None else ''
            
            # Receptor
            receptor = comprobante.find('cfdi:Receptor', ns) or comprobante.find('cfdi3:Receptor', ns)
            rfc_receptor = receptor.get('Rfc', '') if receptor is not None else ''
            nombre_receptor = receptor.get('Nombre', '') if receptor is not None else ''
            
            # Timbre Fiscal (UUID)
            complemento = comprobante.find('.//cfdi:Complemento', ns) or comprobante.find('.//cfdi3:Complemento', ns)
            uuid = ''
            fecha_cancelacion = None
            if complemento is not None:
                timbre = complemento.find('tfd:TimbreFiscalDigital', ns)
                if timbre is not None:
                    uuid = timbre.get('UUID', '')
                    fecha_cancelacion = timbre.get('FechaCancelacion', None)
            
            # Determinar estado: si no tiene fecha de cancelación, está vigente
            estado = 'Cancelado' if fecha_cancelacion else 'Vigente'
            
            return {
                'uuid': uuid,
                'fecha': fecha,
                'serie': serie,
                'folio': folio,
                'rfcEmisor': rfc_emisor,
                'nombreEmisor': nombre_emisor,
                'rfcReceptor': rfc_receptor,
                'nombreReceptor': nombre_receptor,
                'subtotal': float(subtotal),
                'total': float(total),
                'moneda': moneda,
                'tipoComprobante': tipo_comprobante,
                'estado': estado,
                'fechaCancelacion': fecha_cancelacion
            }
            
        except Exception as e:
            print(f"❌ Error al parsear XML: {e}")
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
        
        # Validar que las fechas no sean iguales (SAT requiere rango válido)
        if fecha_inicial and fecha_final and fecha_inicial >= fecha_final:
            error_msg = 'La fecha inicial debe ser anterior a la fecha final. El SAT requiere un rango de fechas válido.'
            print(f"❌ {error_msg}")
            return jsonify({
                'success': False,
                'message': error_msg,
                'sugerencia': 'Selecciona una fecha final que sea al menos 1 día después de la fecha inicial'
            }), 400
        
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
                
                # Si la solicitud está lista (estado 3), descargar y parsear las facturas
                facturas = []
                if verificacion and verificacion.get('estado_solicitud') == '3':
                    print(f"✅ Solicitud lista, descargando paquetes...")
                    paquetes = client.descargar_paquetes(id_solicitud)
                    
                    if paquetes:
                        print(f"📦 Procesando {len(paquetes)} paquetes...")
                        for paquete_data in paquetes:
                            try:
                                # Cada paquete es un diccionario con la data del ZIP
                                facturas_paquete = client.parsear_facturas_de_zip(paquete_data)
                                facturas.extend(facturas_paquete)
                                print(f"✅ Extraídas {len(facturas_paquete)} facturas del paquete")
                            except Exception as e:
                                print(f"⚠️ Error al procesar paquete: {e}")
                                continue
                        
                        print(f"✅ Total de facturas parseadas: {len(facturas)}")
                        
                        # Filtrar facturas canceladas - solo mostrar vigentes por defecto
                        facturas_originales = len(facturas)
                        facturas = [f for f in facturas if f.get('estado') == 'Vigente']
                        facturas_canceladas = facturas_originales - len(facturas)
                        
                        print(f"📊 Facturas vigentes: {len(facturas)}")
                        print(f"📊 Facturas canceladas (filtradas): {facturas_canceladas}")
                
                return jsonify({
                    'success': True,
                    'solicitud': solicitud,
                    'verificacion': verificacion,
                    'id_solicitud': id_solicitud,
                    'facturas': facturas,
                    'stats': {
                        'vigentes': len(facturas),
                        'canceladas_filtradas': facturas_canceladas if 'facturas_originales' in locals() else 0
                    }
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
            # Error 301 - para recibidas significa hay facturas canceladas
            # El SAT NO permite consultar facturas recibidas si hay canceladas en el rango
            tipo_texto = 'emitidas' if tipo_consulta == 'emitidas' else 'recibidas'
            
            print(f"⚠️ Error 301 recibido del SAT")
            print(f"⚠️ Mensaje del SAT: {mensaje}")
            print(f"⚠️ Estado comprobante enviado: {estado_comprobante}")
            print(f"⚠️ Tipo de consulta: {tipo_consulta}")
            
            # Para facturas RECIBIDAS con error 301, significa que hay canceladas
            # y el SAT no permite descargarlas junto con las vigentes
            if tipo_consulta == 'recibidas':
                return jsonify({
                    'success': False,
                    'error_301_recibidas': True,
                    'message': 'El SAT no permite descargar facturas recibidas cuando hay facturas canceladas en el rango de fechas',
                    'sugerencia': 'Intenta reducir el rango de fechas a períodos más pequeños (por ejemplo, un mes a la vez)',
                    'detalle': mensaje,
                    'solicitud': solicitud,
                    'cod_estatus': cod_estatus
                }), 400
            
            # Para emitidas, el error 301 puede significar sin facturas
            return jsonify({
                'success': True,
                'sin_facturas': True,
                'message': f'No tienes facturas {tipo_texto} en estas fechas',
                'detalle': mensaje,
                'solicitud': solicitud,
                'cod_estatus': cod_estatus
            })
        else:
            # Otros códigos de error - también tratarlos como "sin facturas" si no es crítico
            print(f"⚠️ Código de estado no manejado: {cod_estatus}")
            print(f"⚠️ Mensaje: {mensaje}")
            print(f"⚠️ ID Solicitud: {id_solicitud}")
            
            # Código 5002 del SAT = Límite de solicitudes excedido
            if cod_estatus == '5002':
                return jsonify({
                    'success': False,
                    'error_limite': True,
                    'message': 'Has excedido el límite de solicitudes permitidas por el SAT',
                    'detalle': mensaje,
                    'sugerencia': 'El SAT limita la cantidad de solicitudes por RFC. Este límite puede ser diario, mensual o de por vida dependiendo del tipo de cuenta.',
                    'solicitud': solicitud,
                    'cod_estatus': cod_estatus
                }), 400
            
            # Código 404 del SAT = No hay facturas en el rango de fechas (respuesta legítima)
            if cod_estatus == '404':
                tipo_texto = 'emitidas' if tipo_consulta == 'emitidas' else 'recibidas'
                return jsonify({
                    'success': True,
                    'sin_facturas': True,
                    'message': f'No se encontraron facturas {tipo_texto} en el rango de fechas seleccionado',
                    'detalle': 'El SAT confirmó que no existen facturas para este RFC en estas fechas',
                    'solicitud': solicitud,
                    'cod_estatus': cod_estatus
                })
            
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
        # Debug: Imprimir toda la sesión
        print(f"🔍 DEBUG - Session completa: {dict(session)}")
        print(f"🔍 DEBUG - Cookies recibidas: {request.cookies}")
        print(f"🔍 DEBUG - Headers: {dict(request.headers)}")
        
        # Verificar sesión
        if 'usuario_id' not in session:
            print("❌ No hay usuario_id en sesión")
            return jsonify({
                'success': False,
                'message': 'Debes iniciar sesión'
            }), 401
        
        usuario_id = session['usuario_id']
        print(f"📊 Obteniendo datos fiscales para usuario {usuario_id}...")
        
        # Debug: Verificar directamente en la BD
        import sqlite3
        print(f"🔍 DEBUG - Verificando BD directamente desde server.py")
        print(f"🔍 DEBUG - DB_PATH: {database.DB_PATH}")
        try:
            conn = sqlite3.connect(database.DB_PATH, timeout=30)
            cursor = conn.cursor()
            cursor.execute('SELECT usuario_id, rfc, certificado_path FROM datos_fiscales')
            todos_registros = cursor.fetchall()
            print(f"🔍 DEBUG - TODOS los registros en datos_fiscales: {todos_registros}")
            cursor.execute('SELECT usuario_id, rfc FROM datos_fiscales WHERE usuario_id = ?', (usuario_id,))
            registros_usuario = cursor.fetchall()
            print(f"🔍 DEBUG - Registros para usuario {usuario_id}: {registros_usuario}")
            conn.close()
        except Exception as db_error:
            print(f"❌ DEBUG - Error verificando BD: {db_error}")
        
        print(f"🔍 DEBUG - Llamando a database.obtener_datos_fiscales({usuario_id})...")
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
