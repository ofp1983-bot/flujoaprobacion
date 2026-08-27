import streamlit as st
import sqlite3
import uuid
import os
import io
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from pypdf import PdfWriter, PdfReader

# ==========================================
# CONFIGURACIÓN GENERAL Y CREDENCIALES
# ==========================================
DB_FILE = "flujo_documental.db"

# CONFIGURACIÓN NEXTCLOUD (Ajusta estos valores a tu entorno real)
NC_URL = "https://cloud.insdeportescajica.gov.co/remote.php/dav/files/19C87196-1654-4F6B-A835-7255DBC00FF1"
NC_USER = "gdocumental@insdeportescajica.gov.co"
NC_PASS = "nisZG-FgTYd-QfiYy-6qMik-GrMjC" # Se recomienda usar una Contraseña de Aplicación
AUTH = HTTPBasicAuth(NC_USER, NC_PASS)

# URL base para los enlaces (Cámbiala por la URL de tu app en producción)
BASE_URL = "https://flujoaprobacion.streamlit.app/"

# ==========================================
# FUNCIONES DE BASE DE DATOS
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS documentos (
                    id TEXT PRIMARY KEY, 
                    nombre_archivo TEXT, 
                    ruta_archivo TEXT, 
                    observacion_inicial TEXT, 
                    estado TEXT, 
                    total_revisores INTEGER, 
                    total_aprobadores INTEGER, 
                    fecha_creacion TEXT,
                    nombre_elaborador TEXT, 
                    correo_elaborador TEXT, 
                    cargo_elaborador TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS firmas_flujo (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, 
                    doc_id TEXT, 
                    token TEXT UNIQUE,
                    rol TEXT, 
                    nombre TEXT, 
                    cargo TEXT, 
                    correo TEXT, 
                    decision TEXT, 
                    observacion TEXT, 
                    fecha_hora TEXT)''')
    conn.commit()
    conn.close()

init_db()

# ==========================================
# FUNCIONES DE NEXTCLOUD (WEBDAV)
# ==========================================
def subir_a_nextcloud(archivo_bytes, nombre_archivo):
    """Sube un archivo a Nextcloud usando WebDAV (PUT) e imprime errores"""
    url = f"{NC_URL}/{nombre_archivo}"
    try:
        respuesta = requests.put(url, data=archivo_bytes, auth=AUTH)
        
        # Si la respuesta es exitosa (201 Created o 204 No Content)
        if respuesta.status_code in [201, 204]:
            return True
        else:
            # Si falla, mostramos el error exacto en la interfaz de Streamlit
            st.error(f"Fallo en Nextcloud - Código HTTP {respuesta.status_code}: {respuesta.text}")
            return False
            
    except requests.exceptions.RequestException as e:
        # Esto captura errores de red (ej. si el servidor está caído o la URL está mal escrita)
        st.error(f"Error de conexión con el servidor: {e}")
        return False

def descargar_de_nextcloud(nombre_archivo):
    """Descarga un archivo desde Nextcloud en memoria (GET)"""
    url = f"{NC_URL}/{nombre_archivo}"
    respuesta = requests.get(url, auth=AUTH)
    if respuesta.status_code == 200:
        return respuesta.content
    return None

# ==========================================
# FUNCIONES DE GENERACIÓN PDF Y CIERRE
# ==========================================
def generar_hoja_control_temporal(doc_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT rol, nombre, cargo, correo, decision, fecha_hora FROM firmas_flujo WHERE doc_id = ? ORDER BY id ASC", (doc_id,))
    firmas = c.fetchall()
    
    c.execute("""SELECT nombre_archivo, observacion_inicial, nombre_elaborador, 
                 cargo_elaborador, correo_elaborador, fecha_creacion 
                 FROM documentos WHERE id = ?""", (doc_id,))
    doc_info = c.fetchone()
    conn.close()

    temp_hoja = f"hoja_control_{doc_id}.pdf"
    doc = SimpleDocTemplate(temp_hoja, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("<b>MATRIZ DE CONTROL Y APROBACIÓN DOCUMENTAL</b>", styles['Title']))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"<b>Documento:</b> {doc_info[0]}", styles['Normal']))
    story.append(Paragraph(f"<b>Nota inicial:</b> {doc_info[1]}", styles['Normal']))
    story.append(Spacer(1, 15))

    # Encabezados con la columna Cargo
    data = [["Rol", "Nombre Completo", "Cargo", "Correo", "Estado", "Fecha y Hora"]]
    
    # 1. Agregamos al Elaborador como la primera fila
    data.append(["Elaborador", doc_info[2], doc_info[3], doc_info[4], "ELABORADO", doc_info[5]])

    # 2. Agregamos al resto de los actores
    for f in firmas:
        data.append([f[0], f[1], f[2], f[3], f[4], f[5]])

    t = Table(data, colWidths=[65, 110, 100, 110, 65, 80])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1A365D")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,0), 6),
        ('GRID', (0,0), (-1,-1), 1, colors.grey),
        ('FONTSIZE', (0,0), (-1,-1), 7),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(t)
    doc.build(story)
    
    return temp_hoja

def procesar_cierre_documento(doc_id_input, doc_nombre_nextcloud):
    ruta_hoja_temporal = generar_hoja_control_temporal(doc_id_input)
    
    pdf_original_bytes = descargar_de_nextcloud(doc_nombre_nextcloud)
    if not pdf_original_bytes:
        return None, None

    reader_orig = PdfReader(io.BytesIO(pdf_original_bytes))
    reader_hoja = PdfReader(ruta_hoja_temporal)
    writer = PdfWriter()

    for page in reader_orig.pages:
        writer.add_page(page)
    for page in reader_hoja.pages:
        writer.add_page(page)

    pdf_final_io = io.BytesIO()
    writer.write(pdf_final_io)
    pdf_final_bytes = pdf_final_io.getvalue()

    nombre_final_nc = doc_nombre_nextcloud.replace(".pdf", "_FINAL.pdf")
    subir_a_nextcloud(pdf_final_bytes, nombre_final_nc)
    
    if os.path.exists(ruta_hoja_temporal):
        os.remove(ruta_hoja_temporal)
        
    return pdf_final_bytes, nombre_final_nc


# ==========================================
# INTERFAZ DE USUARIO - STREAMLIT
# ==========================================
st.set_page_config(page_title="Gestión y Aprobación Documental", layout="wide")

params = st.query_params
token = params.get("token", None)

if token:
    # ----------------- VISTA REVISOR / APROBADOR (VÍA TOKEN) -----------------
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT doc_id, rol, decision FROM firmas_flujo WHERE token = ?", (token,))
    registro = c.fetchone()

    if not registro:
        st.error("Enlace no válido o expirado.")
    elif registro[2] != "PENDIENTE":
        st.info(f"Ya has completado esta gestión. Estado actual: {registro[2]}")
    else:
        doc_id, rol, _ = registro
        c.execute("SELECT nombre_archivo, ruta_archivo, observacion_inicial FROM documentos WHERE id = ?", (doc_id,))
        doc = c.fetchone()
        
        st.title(f"Gestión de {rol} de Documento")
        st.write(f"**Archivo:** {doc[0]}")
        st.write(f"**Nota inicial:** {doc[2]}")

        # Descarga desde Nextcloud a memoria
        nombre_nextcloud = doc[1]
        pdf_bytes = descargar_de_nextcloud(nombre_nextcloud)

        if pdf_bytes:
            st.download_button("📥 Descargar documento para revisión", data=pdf_bytes, file_name=doc[0], mime="application/pdf")
        else:
            st.error("Error: El documento no se encontró en el repositorio de Nextcloud.")

        st.divider()
        decision = st.radio("Indica tu decisión:", ["Aprobar", "Rechazar/Devolver"])

        with st.form("form_firma"):
            nombre = st.text_input("Nombre completo:")
            cargo = st.text_input("Cargo:")
            correo = st.text_input("Correo electrónico institucional:")
            observaciones = st.text_area("Observaciones (obligatorio si rechaza/devuelve):")
            submit = st.form_submit_button("Confirmar y Registrar")

            if submit:
                if not nombre or not cargo or not correo:
                    st.error("Nombre, cargo y correo son obligatorios.")
                elif decision == "Rechazar/Devolver" and not observaciones.strip():
                    st.error("Debe ingresar una observación para justificar la devolución.")
                else:
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    estado_decision = "APROBADO" if decision == "Aprobar" else "RECHAZADO"
                    
                    c.execute("""UPDATE firmas_flujo 
                                 SET nombre=?, cargo=?, correo=?, decision=?, observacion=?, fecha_hora=? 
                                 WHERE token=?""", (nombre, cargo, correo, estado_decision, observaciones, now, token))
                    
                    if estado_decision == "RECHAZADO":
                        nuevo_estado = "RECHAZADO_REV" if rol == "REVISOR" else "RECHAZADO_APR"
                        c.execute("UPDATE documentos SET estado = ? WHERE id = ?", (nuevo_estado, doc_id))
                    
                    conn.commit()
                    st.success("Acción registrada con éxito. Ya puedes cerrar esta ventana.")
    conn.close()

else:
    # ----------------- PANEL PRINCIPAL / ELABORADOR -----------------
    st.sidebar.title("Menú de Gestión")
    menu = st.sidebar.radio("Opciones", ["1. Iniciar Nuevo Flujo", "2. Estado y Aprobadores", "3. Documentos Finalizados"])

    if menu == "1. Iniciar Nuevo Flujo":
        st.header("Carga de Documento e Inicio de Flujo")
        
        st.subheader("Datos del Elaborador")
        col1, col2, col3 = st.columns(3)
        with col1:
            nombre_elab = st.text_input("Tu Nombre Completo:")
        with col2:
            cargo_elab = st.text_input("Tu Cargo:")
        with col3:
            correo_elab = st.text_input("Tu Correo Institucional:")

        st.subheader("Configuración del Documento")
        archivo = st.file_uploader("Selecciona el documento (PDF)", type=["pdf"])
        num_revisores = st.number_input("Número de Revisores requeridos:", min_value=1, max_value=10, value=1)
        observacion = st.text_area("Nota / Observaciones (Ej: Primera versión / Ajustes realizados):")

        if st.button("Crear Flujo y Generar Enlaces"):
            if archivo and observacion and nombre_elab and cargo_elab and correo_elab:
                doc_id = str(uuid.uuid4())[:8]
                nombre_guardado = f"{doc_id}_{archivo.name}"
                
                with st.spinner("Subiendo a Nextcloud..."):
                    exito_subida = subir_a_nextcloud(archivo.getvalue(), nombre_guardado)
                
                if exito_subida:
                    conn = sqlite3.connect(DB_FILE)
                    c = conn.cursor()
                    fecha_creacion = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    c.execute("""INSERT INTO documentos VALUES (?, ?, ?, ?, 'REVISION', ?, 0, ?, ?, ?, ?)""",
                              (doc_id, archivo.name, nombre_guardado, observacion, num_revisores, 
                               fecha_creacion, nombre_elab, correo_elab, cargo_elab))
                    
                    tokens = []
                    for _ in range(num_revisores):
                        tok = str(uuid.uuid4())
                        c.execute("""INSERT INTO firmas_flujo (doc_id, token, rol, decision) 
                                     VALUES (?, ?, 'REVISOR', 'PENDIENTE')""", (doc_id, tok))
                        tokens.append(tok)

                    conn.commit()
                    conn.close()

                    st.success(f"Documento guardado en Nextcloud. Flujo creado (ID: {doc_id}).")
                    st.info("Comparte los siguientes enlaces con los revisores:")
                    for i, tok in enumerate(tokens, 1):
                        st.code(f"{BASE_URL}/?token={tok}", language="text")
                else:
                    st.error("Error de comunicación con Nextcloud. Revisa las credenciales o la URL.")
            else:
                st.warning("Por favor, completa todos los campos obligatorios y adjunta un documento.")

    elif menu == "2. Estado y Aprobadores":
        st.header("Control de Estados y Asignación de Aprobadores")
        doc_id_input = st.text_input("Ingresa el ID del Documento (Ej: abc123df):")
        
        if doc_id_input:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT nombre_archivo, ruta_archivo, estado, total_revisores FROM documentos WHERE id = ?", (doc_id_input,))
            doc = c.fetchone()

            if doc:
                st.write(f"**Archivo original:** {doc[0]} | **Estado Actual:** `{doc[2]}`")
                
                # Mostrar firmas de revisores/aprobadores
                c.execute("SELECT rol, nombre, cargo, decision, fecha_hora FROM firmas_flujo WHERE doc_id = ?", (doc_id_input,))
                firmas = c.fetchall()
                if firmas:
                    st.table(firmas)

                # Verificar Revisores
                c.execute("SELECT COUNT(*) FROM firmas_flujo WHERE doc_id = ? AND rol = 'REVISOR' AND decision = 'APROBADO'", (doc_id_input,))
                rev_aprobados = c.fetchone()[0]

                if doc[2] == 'REVISION' and rev_aprobados == doc[3]:
                    st.success("✅ Todos los revisores han aprobado el documento.")
                    st.subheader("Paso 2: Configurar Aprobadores")
                    num_apr = st.number_input("Número de Aprobadores requeridos:", min_value=1, max_value=10, value=1)
                    
                    if st.button("Generar Enlaces para Aprobadores"):
                        tokens_apr = []
                        for _ in range(num_apr):
                            tok = str(uuid.uuid4())
                            c.execute("""INSERT INTO firmas_flujo (doc_id, token, rol, decision) 
                                         VALUES (?, ?, 'APROBADOR', 'PENDIENTE')""", (doc_id_input, tok))
                            tokens_apr.append(tok)
                        
                        c.execute("UPDATE documentos SET estado = 'APROBACION', total_aprobadores = ? WHERE id = ?", (num_apr, doc_id_input))
                        conn.commit()
                        st.success("Enlaces de aprobación generados con éxito:")
                        for tok in tokens_apr:
                            st.code(f"{BASE_URL}/?token={tok}", language="text")
                            
                elif doc[2] == 'APROBACION':
                    c.execute("SELECT COUNT(*) FROM firmas_flujo WHERE doc_id = ? AND rol = 'APROBADOR' AND decision = 'APROBADO'", (doc_id_input,))
                    apr_aprobados = c.fetchone()[0]
                    c.execute("SELECT total_aprobadores FROM documentos WHERE id = ?", (doc_id_input,))
                    tot_apr = c.fetchone()[0]

                    if apr_aprobados == tot_apr:
                        st.success("🎉 ¡Todos los aprobadores han firmado! El flujo está listo para cerrarse.")
                        if st.button("Generar Documento Final con Hoja de Firmas"):
                            with st.spinner("Descargando, uniendo PDFs y subiendo a Nextcloud..."):
                                pdf_final_bytes, nombre_final_nc = procesar_cierre_documento(doc_id_input, doc[1])
                                
                                if pdf_final_bytes:
                                    c.execute("UPDATE documentos SET estado = 'COMPLETADO' WHERE id = ?", (doc_id_input,))
                                    conn.commit()
                                    st.success(f"Documento final generado y guardado en Nextcloud como: `{nombre_final_nc}`")
                                    st.download_button("📥 Descargar PDF Final", data=pdf_final_bytes, file_name=nombre_final_nc, mime="application/pdf")
                                else:
                                    st.error("Hubo un error obteniendo el archivo original desde Nextcloud.")
            else:
                st.error("Documento no encontrado. Verifica el ID.")
            conn.close()

    elif menu == "3. Documentos Finalizados":
        st.header("Repositorio de Documentos Completados")
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("""SELECT id, nombre_archivo, ruta_archivo, fecha_creacion, nombre_elaborador 
                     FROM documentos WHERE estado = 'COMPLETADO' ORDER BY fecha_creacion DESC""")
        docs = c.fetchall()
        
        if docs:
            for d in docs:
                with st.expander(f"📄 {d[1]} (ID: {d[0]}) - Elaborado por: {d[4]}"):
                    st.write(f"**Fecha de inicio del flujo:** {d[3]}")
                    nombre_final_nc = d[2].replace(".pdf", "_FINAL.pdf")
                    st.write(f"**Nombre en Nextcloud:** `{nombre_final_nc}`")
                    
                    if st.button(f"Descargar de Nextcloud", key=d[0]):
                        archivo_bytes = descargar_de_nextcloud(nombre_final_nc)
                        if archivo_bytes:
                            st.download_button("📥 Confirmar Descarga", data=archivo_bytes, file_name=nombre_final_nc, mime="application/pdf", key=f"dl_{d[0]}")
                        else:
                            st.error("El archivo final ya no se encuentra en Nextcloud.")
        else:
            st.info("Aún no hay documentos con el flujo completado.")
        conn.close()
