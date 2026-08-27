import streamlit as st
import sqlite3
import uuid
import os
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from pypdf import PdfWriter, PdfReader

DB_FILE = "flujo_documental.db"
UPLOAD_DIR = "documentos_subidos"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ----------------- BASE DE DATOS -----------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS documentos (
                    id TEXT PRIMARY KEY, nombre_archivo TEXT, ruta_archivo TEXT, 
                    observacion_inicial TEXT, estado TEXT, total_revisores INTEGER, 
                    total_aprobadores INTEGER, fecha_creacion TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS firmas_flujo (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT, token TEXT UNIQUE,
                    rol TEXT, nombre TEXT, correo TEXT, decision TEXT, 
                    observacion TEXT, fecha_hora TEXT)''')
    conn.commit()
    conn.close()

init_db()

# ----------------- GENERADOR DE PÁGINA FINAL -----------------
def generar_hoja_control(doc_id, ruta_original):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT rol, nombre, correo, decision, fecha_hora, observacion FROM firmas_flujo WHERE doc_id = ?", (doc_id,))
    firmas = c.fetchall()
    c.execute("SELECT nombre_archivo, observacion_inicial FROM documentos WHERE id = ?", (doc_id,))
    doc_info = c.fetchone()
    conn.close()

    temp_hoja = f"hoja_control_{doc_id}.pdf"
    doc = SimpleDocTemplate(temp_hoja, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("<b>HOJA DE CONTROL Y CONTROL DE CAMBIOS / FIRMAS</b>", styles['Title']))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"<b>Documento:</b> {doc_info[0]}", styles['Normal']))
    story.append(Paragraph(f"<b>Nota inicial del elaborador:</b> {doc_info[1]}", styles['Normal']))
    story.append(Spacer(1, 15))

    data = [["Rol", "Nombre Completo", "Correo Institucional", "Estado", "Fecha y Hora"]]
    for f in firmas:
        data.append([f[0], f[1], f[2], f[3], f[4]])

    t = Table(data, colWidths=[80, 140, 150, 80, 100])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1A365D")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,0), 6),
        ('GRID', (0,0), (-1,-1), 1, colors.grey),
        ('FONTSIZE', (0,0), (-1,-1), 8),
    ]))
    story.append(t)
    doc.build(story)

    # Unir la hoja al final del PDF
    writer = PdfWriter()
    reader_orig = PdfReader(ruta_original)
    reader_hoja = PdfReader(temp_hoja)

    for page in reader_orig.pages:
        writer.add_page(page)
    for page in reader_hoja.pages:
        writer.add_page(page)

    ruta_final = ruta_original.replace(".pdf", "_FINAL.pdf")
    with open(ruta_final, "wb") as f_out:
        writer.write(f_out)
    
    if os.path.exists(temp_hoja):
        os.remove(temp_hoja)
    return ruta_final

# ----------------- VISTAS DE LA APLICACIÓN -----------------
st.set_page_config(page_title="Flujo de Aprobación de Documentos", layout="wide")

# Obtener parámetros de URL
params = st.query_params
token = params.get("token", None)

if token:
    # ----------------- VISTA REVISOR / APROBADOR -----------------
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT doc_id, rol, decision FROM firmas_flujo WHERE token = ?", (token,))
    registro = c.fetchone()

    if not registro:
        st.error("Enlace no válido o expirado.")
    elif registro[2] != "PENDIENTE":
        st.info(f"Ya has completado esta gestión ({registro[2]}).")
    else:
        doc_id, rol, _ = registro
        c.execute("SELECT nombre_archivo, ruta_archivo, observacion_inicial FROM documentos WHERE id = ?", (doc_id,))
        doc = c.fetchone()
        
        st.title(f"Gestión de {rol} de Documento")
        st.write(f"**Archivo:** {doc[0]}")
        st.write(f"**Nota del Elaborador:** {doc[2]}")

        with open(doc[1], "rb") as pdf_file:
            st.download_button("📥 Descargar documento para revisión", pdf_file, file_name=doc[0])

        st.divider()
        decision = st.radio("Indica tu decisión:", ["Aprobar", "Rechazar/Devolver"])

        with st.form("form_firma"):
            nombre = st.text_input("Nombre completo:")
            correo = st.text_input("Correo electrónico institucional:")
            observaciones = st.text_area("Observaciones (obligatorio si rechaza):")
            submit = st.form_submit_button("Confirmar y Registrar")

            if submit:
                if not nombre or not correo:
                    st.error("Nombre y correo son obligatorios.")
                elif decision == "Rechazar/Devolver" and not observaciones.strip():
                    st.error("Debe ingresar una observación para justificar la devolución.")
                else:
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    estado_decision = "APROBADO" if decision == "Aprobar" else "RECHAZADO"
                    
                    c.execute("""UPDATE firmas_flujo 
                                 SET nombre=?, correo=?, decision=?, observacion=?, fecha_hora=? 
                                 WHERE token=?""", (nombre, correo, estado_decision, observaciones, now, token))
                    
                    # Si rechaza, actualiza el estado general del documento
                    if estado_decision == "RECHAZADO":
                        nuevo_estado = "RECHAZADO_REV" if rol == "REVISOR" else "RECHAZADO_APR"
                        c.execute("UPDATE documentos SET estado = ? WHERE id = ?", (nuevo_estado, doc_id))
                    
                    conn.commit()
                    st.success("Acción registrada con éxito. Ya puedes cerrar esta ventana.")
    conn.close()

else:
    # ----------------- PANEL PRINCIPAL / ELABORADOR -----------------
    st.sidebar.title("Menú")
    menu = st.sidebar.radio("Opciones", ["1. Iniciar Nuevo Flujo", "2. Estado y Aprobadores", "3. Documentos Finalizados"])

    if menu == "1. Iniciar Nuevo Flujo":
        st.header("Carga de Documento e Inicio de Flujo")
        archivo = st.file_uploader("Selecciona el documento (PDF)", type=["pdf"])
        num_revisores = st.number_input("Número de Revisores requeridos:", min_value=1, max_value=10, value=1)
        observacion = st.text_area("Nota / Observaciones del Elaborador (Ej: Primera versión / Ajustes realizados):")

        if st.button("Crear Flujo y Generar Enlaces de Revisión"):
            if archivo and observacion:
                doc_id = str(uuid.uuid4())[:8]
                ruta = os.path.join(UPLOAD_DIR, f"{doc_id}_{archivo.name}")
                with open(ruta, "wb") as f:
                    f.write(archivo.getbuffer())

                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute("""INSERT INTO documentos VALUES (?, ?, ?, ?, 'REVISION', ?, 0, ?)""",
                          (doc_id, archivo.name, ruta, observacion, num_revisores, datetime.now().strftime("%Y-%m-%d %H:%M")))

                tokens = []
                for _ in range(num_revisores):
                    tok = str(uuid.uuid4())
                    c.execute("""INSERT INTO firmas_flujo (doc_id, token, rol, decision) 
                                 VALUES (?, ?, 'REVISOR', 'PENDIENTE')""", (doc_id, tok))
                    tokens.append(tok)

                conn.commit()
                conn.close()

                st.success(f"Flujo creado (ID: {doc_id}). Comparte los siguientes enlaces con los revisores:")
                for i, tok in enumerate(tokens, 1):
                    st.code(f"http://localhost:8501/?token={tok}", language="text")
            else:
                st.error("Debes subir un archivo PDF y colocar una observación.")

    elif menu == "2. Estado y Aprobadores":
        st.header("Control de Estados y Asignación de Aprobadores")
        doc_id_input = st.text_input("Ingresa el ID del Documento:")
        
        if doc_id_input:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT nombre_archivo, ruta_archivo, estado, total_revisores FROM documentos WHERE id = ?", (doc_id_input,))
            doc = c.fetchone()

            if doc:
                st.write(f"**Archivo:** {doc[0]} | **Estado Actual:** `{doc[2]}`")
                
                # Mostrar estado de revisiones
                c.execute("SELECT rol, nombre, correo, decision, observacion, fecha_hora FROM firmas_flujo WHERE doc_id = ?", (doc_id_input,))
                firmas = c.fetchall()
                st.table(firmas)

                # Verificar si todos los revisores aprobaron
                c.execute("SELECT COUNT(*) FROM firmas_flujo WHERE doc_id = ? AND rol = 'REVISOR' AND decision = 'APROBADO'", (doc_id_input,))
                rev_aprobados = c.fetchone()[0]

                if doc[2] == 'REVISION' and rev_aprobados == doc[3]:
                    st.success("✅ Todos los revisores han aprobado.")
                    st.subheader("Configurar Aprobadores")
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
                        st.success("Enlaces de aprobación generados:")
                        for tok in tokens_apr:
                            st.code(f"http://localhost:8501/?token={tok}", language="text")
                            
                elif doc[2] == 'APROBACION':
                    c.execute("SELECT COUNT(*) FROM firmas_flujo WHERE doc_id = ? AND rol = 'APROBADOR' AND decision = 'APROBADO'", (doc_id_input,))
                    apr_aprobados = c.fetchone()[0]
                    c.execute("SELECT total_aprobadores FROM documentos WHERE id = ?", (doc_id_input,))
                    tot_apr = c.fetchone()[0]

                    if apr_aprobados == tot_apr:
                        st.success("🎉 ¡Todos los aprobadores han firmado!")
                        if st.button("Generar Documento Final con Hoja de Firmas"):
                            ruta_final = generar_hoja_control(doc_id_input, doc[1])
                            c.execute("UPDATE documentos SET estado = 'COMPLETADO' WHERE id = ?", (doc_id_input,))
                            conn.commit()
                            st.success("Documento final generado.")
                            with open(ruta_final, "rb") as f_final:
                                st.download_button("📥 Descargar PDF Final Estampado", f_final, file_name=f"{doc[0]}_FINAL.pdf")
            else:
                st.error("Documento no encontrado.")
            conn.close()

    elif menu == "3. Documentos Finalizados":
        st.header("Repositorio de Documentos Completados")
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT id, nombre_archivo, fecha_creacion FROM documentos WHERE estado = 'COMPLETADO'")
        docs = c.fetchall()
        for d in docs:
            st.write(f"📄 **ID:** `{d[0]}` | **Archivo:** {d[1]} | **Fecha:** {d[2]}")
        conn.close()