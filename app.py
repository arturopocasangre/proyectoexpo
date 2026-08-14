from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime, timedelta
import mysql.connector
from pymysql.cursors import DictCursor
from collections import defaultdict
import psycopg2.extras
import stripe
import pymysql
import uuid
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import jsonify

app = Flask(__name__)
app.secret_key = "clave_secreta_segura"


# -------------------
# Conexión a MySQL
# -------------------
def get_db_connection():
    return pymysql.connect(
        host="localhost",
        user="root",        # Usuario MySQL
        password="",        # Contraseña MySQL
        database="happy_paws",
        cursorclass=pymysql.cursors.DictCursor
    )

# -------------------
# Rutas principales
# -------------------
@app.route("/")
def inicio():
    return render_template("index.html")

@app.route("/contacto")
def contacto():
    return render_template("contacto.html")

@app.route("/nosotros")
def nosotros():
    return render_template("nosotros.html")

@app.route("/servicios")
def servicios():
    return render_template("servicios.html")

@app.route("/tienda")
def tienda():
    return render_template("tienda.html")

@app.route("/preguntas")
def preguntas():
    return render_template("preguntas.html")

@app.route("/guia-videollamadas")
def guia_videollamadas():
    return render_template("guia-videollamadas.html")

@app.route("/terminos")
def terminos():
    return render_template("terminos.html")

@app.route("/privacidad")
def privacidad():
    return render_template("privacidad.html")

@app.route('/alimentos')
def alimentos():
    return render_template('alimentos.html')

@app.route('/accesorios')
def accesorios():
    return render_template('accesorios.html')

@app.route('/higiene')
def higiene():
    return render_template('higiene.html')

# -------------------
# Flujo de citas
# -------------------
@app.route("/consulta/<int:cita_id>")
def consulta(cita_id):
    conn = get_db_connection()
    with conn.cursor(pymysql.cursors.DictCursor) as cursor:
        cursor.execute("SELECT link_consulta FROM citas WHERE id=%s", (cita_id,))
        cita = cursor.fetchone()
    conn.close()

    if not cita:
        return "❌ Consulta no encontrada."

    # Si link_consulta es "https://meet.jit.si/HappyPawsSala123"
    # extraemos solo "HappyPawsSala123"
    room_name = cita["link_consulta"].split("/")[-1]

    return render_template("consulta.html", room_name=room_name)



# Claves de Stripe 
stripe.api_key = "sk_test_51SBPpzJun2eTyNcsHGM1ldwCVcGn59AJeOZMIOHtH8HZTnT9flFlq4e8nzc2QOeoURq3zUkJP4DMZNNtbwkeJ7i600JG1Gc9ix"

# -------------------
# Checkout
# -------------------
@app.route("/checkout/<int:cita_id>")
def checkout(cita_id):
	
    # Verificar que el usuario esté logueado
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    # Aquí definimos cliente_id correctamente
    cliente_id = session["usuario_id"]
    conn = get_db_connection()
    with conn.cursor() as cursor:
        # Asociar cliente a la cita
        cursor.execute("UPDATE citas SET estado='pendiente', cliente_id=%s WHERE id=%s", (cliente_id, cita_id))
        conn.commit()
        cursor.execute("""
            SELECT c.id, c.fecha, c.hora, c.precio, cl.nombre AS cliente_nombre, cl.email AS cliente_email
            FROM citas c
            JOIN usuarios cl ON c.cliente_id = cl.id
            WHERE c.id=%s
        """, (cita_id,))
        cita = cursor.fetchone()
    conn.close()

    if not cita:
        return "❌ Error: la cita no existe o no tiene cliente asociado."

    return render_template("checkout.html", cita=cita, cliente_nombre=cita["cliente_nombre"], cita_id=cita_id)


@app.route("/cancel/<int:cita_id>")
def cancel(cita_id):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("UPDATE citas SET estado='disponible', cliente_id=null WHERE id=%s", (cita_id,))
        conn.commit()
    conn.close()
    return redirect(url_for("panel_cliente", cita_id=cita_id))


# -------------------
# Stripe Checkout
# -------------------
@app.route("/stripe_checkout/<int:cita_id>", methods=["POST"])
def stripe_checkout(cita_id):
    # Traer el precio de la cita desde la base de datos
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT precio FROM citas WHERE id=%s", (cita_id,))
        cita = cursor.fetchone()
    conn.close()

    if not cita:
        return "❌ Error: la cita no existe."

    # Stripe espera el precio en centavos (ej. $20 = 2000)
    precio_centavos = int(float(cita["precio"]) * 100)

    # Crear sesión de pago en Stripe
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": "Consulta veterinaria",
                },
                "unit_amount": precio_centavos,
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url=url_for("pago_success", cita_id=cita_id, _external=True) + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=url_for("checkout", cita_id=cita_id, _external=True),
    )
    return redirect(session.url, code=303)

# -------------------
# Pago confirmado
# -------------------
@app.route("/pago/success/<int:cita_id>")
def pago_success(cita_id):
    # Recuperar el session_id desde querystring
    session_id = request.args.get("session_id")
    if not session_id:
        return "❌ Error: falta session_id"

    # Recuperar la sesión de Stripe
    session = stripe.checkout.Session.retrieve(session_id)

    # Obtener el PaymentIntent ID (referencia de pago)
    referencia_pago = session.payment_intent

    # Traer datos de la cita
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT c.fecha, c.hora, cl.nombre AS cliente_nombre, cl.email AS cliente_email
            FROM citas c
            JOIN usuarios cl ON c.cliente_id = cl.id
            WHERE c.id=%s
        """, (cita_id,))
        cita = cursor.fetchone()
    conn.close()

    if not cita:
        return "❌ Error: la cita no existe o no tiene cliente asociado."

    enlace_jitsi = f"https://meet.jit.si/happy-paws-{cita_id}"

    # Guardar enlace y referencia de pago en la cita
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            UPDATE citas 
            SET link_consulta=%s, estado='pagada', referencia_pago=%s 
            WHERE id=%s
        """, (enlace_jitsi, referencia_pago, cita_id))
        conn.commit()
    conn.close()

    # Enviar correo de confirmación
    enviar_correo(cita["cliente_email"], cita["cliente_nombre"], cita["fecha"], cita["hora"], enlace_jitsi)

    return redirect(url_for("panel_cliente"))



# -------------------
# envia confirmacion
# -------------------
def enviar_correo(destinatario, nombre, fecha, hora, enlace):
    remitente = "HappyPawsVet2026@gmail.com"
    mensaje = f"""
    Hola {nombre},

    Tu cita ha sido confirmada:
    📅 Fecha: {fecha}
    ⏰ Hora: {hora}
    🔗 Enlace de consulta: {enlace}

    ¡Gracias por confiar en Happy Paws Vet!
    """

    msg = MIMEText(mensaje, "plain", "utf-8")
    msg["Subject"] = "Confirmación de cita - Happy Paws Vet"
    msg["From"] = remitente
    msg["To"] = destinatario

    # Configuración SMTP (ejemplo con Gmail)
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login("HappyPawsVet2026@gmail.com ", "acxu anym uwvs brgd")

        server.sendmail(remitente, destinatario, msg.as_string())



# -------------------
# guardar cliente y redirigir al checkout
# -------------------
#
#
#

# -------------------
# Panel admin: listar configuración
# -------------------
@app.route("/admin/configuracion")
def admin_configuracion():
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM configuracion_cupos ORDER BY dia_semana")
        configuraciones = cursor.fetchall()
    conn.close()
    return render_template("admin_configuracion.html", configuraciones=configuraciones)

# -------------------
# Agregar configuración
# -------------------
@app.route("/admin/configuracion/agregar", methods=["POST"])
def admin_configuracion_agregar():
    dia_semana = request.form["dia_semana"]
    hora_inicio = request.form["hora_inicio"]
    hora_fin = request.form["hora_fin"]
    intervalo = request.form["intervalo"]
    precio = request.form["precio"]

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            INSERT INTO configuracion_cupos (dia_semana, hora_inicio, hora_fin, intervalo, precio)
            VALUES (%s, %s, %s, %s, %s)
        """, (dia_semana, hora_inicio, hora_fin, intervalo, precio))
        conn.commit()
    conn.close()
    return redirect(url_for("admin_configuracion"))


# -------------------
# Eliminar configuración
# -------------------
@app.route("/admin/configuracion/eliminar/<int:id>", methods=["POST"])
def admin_configuracion_eliminar(id):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM configuracion_cupos WHERE id=%s", (id,))
        conn.commit()
    conn.close()
    return redirect(url_for("admin_configuracion"))


@app.route("/logout")
def logout():
    session.clear()  # elimina toda la información de la sesión
    return redirect(url_for("inicio"))

# -------------------
# Panel Admin
# -------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        conn = get_db_connection()
        cursor = conn.cursor(DictCursor)   # 👈 igual que en mysqlclient
        cursor.execute("SELECT * FROM usuarios WHERE email=%s and activo=1", (email,))
        usuario = cursor.fetchone()
        cursor.close()
        conn.close()

        if usuario and check_password_hash(usuario["password"], password):
            session["usuario_id"] = usuario["id"]
            session["rol"] = usuario["rol"]

            if usuario["rol"] == "admin":
                return redirect(url_for("panel_admin"))
            elif usuario["rol"] == "veterinario":
                return redirect(url_for("panel_veterinario"))
            else:
                return redirect(url_for("panel_cliente"))
        else:
            return "❌ Usuario o contraseña incorrectos"

    return render_template("login.html")



# -------------------
# 📌 Paneles según rol
# -------------------
@app.route("/panel/admin")
def panel_admin():
    if session.get("rol") != "admin":
        return "Acceso denegado"

    conn = get_db_connection()
    with conn.cursor() as cursor:
        # Usuarios
        cursor.execute("SELECT * FROM usuarios where rol <> 'cliente'")
        usuarios = cursor.fetchall()

        # Clientes
        cursor.execute("SELECT * FROM usuarios where rol ='cliente'")
        clientes = cursor.fetchall()

        # Citas
        cursor.execute("""
            SELECT c.id, c.fecha, c.hora, c.estado, c.link_consulta,
                   nombre AS cliente_nombre, cl.email AS cliente_email
            FROM citas c
            LEFT JOIN usuarios cl ON c.cliente_id = cl.id
            ORDER BY c.fecha, c.hora desc
        """)
        citas = cursor.fetchall()
    conn.close()

    return render_template("panel_admin.html", usuarios=usuarios, clientes=clientes, citas=citas)


@app.route("/panel/veterinario")
def panel_veterinario():
    if session.get("rol") != "veterinario":
        return "Acceso denegado"

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT c.fecha, c.hora, c.estado, c.link_consulta,cl.nombre AS cliente_nombre,
                   cl.email AS cliente_email, cl.telefono AS cliente_telefono
            FROM citas c
            JOIN usuarios cl ON c.cliente_id = cl.id
            WHERE c.estado IN ('reservada','pagada')
            ORDER BY c.fecha, c.hora
        """)
        citas = cursor.fetchall()
    conn.close()

    return render_template("panel_veterinario.html", citas=citas)



@app.route("/panel/cliente")
def panel_cliente():
    if session.get("rol") != "cliente":
        return redirect(url_for("login"))

    usuario_id = session.get("usuario_id")

    conn = get_db_connection()
    with conn.cursor() as cursor:
        # Traer el cliente asociado al usuario
        cursor.execute("SELECT cliente_id FROM usuarios WHERE id=%s", (usuario_id,))
        usuario = cursor.fetchone()

        if not usuario:
            conn.close() # Cerramos antes de salir
            return "❌ Error: usuario no encontrado."

        cliente_id = usuario["cliente_id"]

        # Traer citas confirmadas del cliente (Cambiado a filtrar por cliente_id real)
        cursor.execute("""
            SELECT id, fecha, hora, estado, link_consulta
            FROM citas
            WHERE cliente_id=%s
            AND estado = 'pagada'
            AND TIMESTAMP(fecha, hora) > (NOW() - INTERVAL 2 HOUR)
            ORDER BY fecha, hora
        """, (usuario_id,))
        citas = cursor.fetchall()

        # Traer cupos disponibles
        cursor.execute("""
            SELECT * 
            FROM citas 
            WHERE estado='disponible' and cliente_id is null
              AND TIMESTAMP(fecha, hora) > NOW() 
            ORDER BY fecha, hora
        """)
        cupos = cursor.fetchall()
        
        # Traer citas pasadas (pagadas pero ya vencidas)
        cursor.execute("""
            SELECT * 
            FROM citas 
            WHERE cliente_id=%s 
              AND estado='pagada' 
              AND TIMESTAMP(fecha, hora) < (NOW() - INTERVAL 2 HOUR) 
            ORDER BY fecha, hora
        """, (usuario_id,))
        vencidas = cursor.fetchall()

    conn.close()

    for cita in citas:
        fecha_hora = datetime.strptime(f"{cita['fecha']} {cita['hora']}", "%Y-%m-%d %H:%M:%S")
        ahora = datetime.now()
        # habilitar desde 10 minutos antes hasta 30 minutos después
        inicio = fecha_hora - timedelta(minutes=10)
        fin = fecha_hora + timedelta(minutes=30)
        cita["habilitar"] = (inicio <= ahora <= fin)

    # Creamos un diccionario agrupado por fecha
    cupos_agrupados = defaultdict(list)
    for cita in cupos:
        # 1. Formateamos la fecha de manera limpia (Ej: "2026-07-08")
        if hasattr(cita['fecha'], 'strftime'):
            fecha_str = cita['fecha'].strftime('%Y-%m-%d')
        else:
            fecha_str = str(cita['fecha'])
            
        # 2. Formateamos la hora de manera limpia (Ej: "14:00")
        # Si el driver de base de datos te devuelve un objeto 'timedelta' o 'time', lo formateamos:
        if hasattr(cita['hora'], 'strftime'):
            hora_str = cita['hora'].strftime('%H:%M')
        else:
            # En algunos conectores de MySQL las columnas TIME regresan como timedelta
            # Esto remueve los segundos extras si vienen como string "14:00:00"
            hora_str = str(cita['hora'])[:5] 
        
        cupos_agrupados[fecha_str].append({
            'id': cita['id'],
            'hora': hora_str  # <-- Enviamos texto plano seguro para Jinja
        })
    
    # Convertimos a diccionario normal para Jinja
    cupos_listos = dict(cupos_agrupados)

    return render_template("panel_cliente.html", cupos=cupos_listos, citas=citas, vencidas=vencidas)

# -------------------
# Rutas para gestión
# -------------------
@app.route("/admin/usuario/nuevo", methods=["GET","POST"])
def nuevo_usuario():
    if session.get("rol") != "admin":
        return "Acceso denegado"

    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        rol = request.form["rol"]
        activo = request.form["activo"]
        nombre = request.form["nombre"]
        telefono = request.form["telefono"]
        direccion = request.form["direccion"]

        hashed_pw = generate_password_hash(password)

        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO usuarios (email, password, rol, activo, nombre, telefono, direccion)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (email, hashed_pw, rol, activo, nombre, telefono, direccion))
            conn.commit()
        conn.close()
        return redirect(url_for("panel_admin"))

    # En creación no hay usuario, se pasa None
    return render_template("usuario_form.html", usuario=None)



@app.route("/admin/usuario/editar/<int:usuario_id>", methods=["GET","POST"])
def editar_usuario(usuario_id):
    if session.get("rol") != "admin":
        return "Acceso denegado"

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM usuarios WHERE id=%s", (usuario_id,))
        usuario = cursor.fetchone()

    if request.method == "POST":
        # Recoger todos los campos del formulario
        email = request.form["email"]
        password = request.form.get("password")
        rol = request.form["rol"]
        activo = request.form.get("activo")  # checkbox o select en tu formulario
        nombre = request.form.get("nombre")
        telefono = request.form.get("telefono")
        direccion = request.form.get("direccion")

        with conn.cursor() as cursor:
            if password:  # si se ingresó nueva contraseña
                hashed_pw = generate_password_hash(password)
                cursor.execute("""
                    UPDATE usuarios 
                    SET email=%s, password=%s, rol=%s, activo=%s, nombre=%s, telefono=%s, direccion=%s
                    WHERE id=%s
                """, (email, hashed_pw, rol, activo, nombre, telefono, direccion, usuario_id))
            else:  # si no se cambia la contraseña
                cursor.execute("""
                    UPDATE usuarios 
                    SET email=%s, rol=%s, activo=%s, nombre=%s, telefono=%s, direccion=%s
                    WHERE id=%s
                """, (email, rol, activo, nombre, telefono, direccion, usuario_id))
            conn.commit()
        conn.close()
        return redirect(url_for("panel_admin"))

    conn.close()
    return render_template("usuario_form.html", usuario=usuario)


@app.route("/admin/cita/nueva", methods=["GET","POST"])
def nueva_cita():
    if session.get("rol") != "admin":
        return "Acceso denegado"

    if request.method == "POST":
        fecha = request.form["fecha"]
        hora = request.form["hora"]
        precio = request.form["precio"]
        cliente = request.form.get("cliente") or None  # si no elige, será None
        estado = request.form["estado"]
        
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO citas (fecha, hora, precio, cliente_id, estado)
                VALUES (%s, %s, %s, %s, %s)
            """, (fecha, hora, precio, cliente, estado))
            conn.commit()
        conn.close()
        return redirect(url_for("panel_admin"))

    # Traer clientes para el select
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM usuarios WHERE rol='cliente'")
        clientes = cursor.fetchall()
    conn.close()

    # En creación no hay cita, se pasa None
    return render_template("cita_form.html", cita=None, clientes=clientes)


@app.route("/admin/cita/editar/<int:cita_id>", methods=["GET","POST"])
def editar_cita(cita_id):
    if session.get("rol") != "admin":
        return "Acceso denegado"

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM citas WHERE id=%s", (cita_id,))
        cita = cursor.fetchone()
        
        # Listado de clientes
        cursor.execute("SELECT * FROM usuarios WHERE rol='cliente'")
        clientes = cursor.fetchall()

    if request.method == "POST":
        fecha = request.form["fecha"]
        hora = request.form["hora"]
        precio = request.form["precio"]
        estado = request.form["estado"]
        cliente = request.form.get("cliente") or None

        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE citas 
                SET fecha=%s, hora=%s, precio=%s, estado=%s, cliente_id=%s 
                WHERE id=%s
            """, (fecha, hora, precio, estado, cliente, cita_id))
            conn.commit()
        conn.close()
        return redirect(url_for("panel_admin"))

    conn.close()
    return render_template("cita_form.html", cita=cita, clientes=clientes)


@app.route("/admin/cita/<int:cita_id>/crear_enlace")
def crear_enlace(cita_id):
    if session.get("rol") != "admin":
        return "Acceso denegado"

    # Aquí generas el enlace (ejemplo: Zoom, Jitsi, etc.)
    nuevo_link = f"https://meet.jit.si/happy-paws-{cita_id}"

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("UPDATE citas SET link_consulta=%s WHERE id=%s", (nuevo_link, cita_id))
        conn.commit()
    conn.close()

    return redirect(url_for("panel_admin"))

    

@app.route("/admin/cita/eliminar/<int:cita_id>", methods=["POST"])
def eliminar_cita(cita_id):
    if session.get("rol") != "admin":
        return "Acceso denegado"

    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM citas WHERE id=%s", (cita_id,))
        conn.commit()
    conn.close()

    return redirect(url_for("panel_admin"))


from werkzeug.security import generate_password_hash

@app.route("/registro", methods=["GET", "POST"])
def registro():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        nombre = request.form.get("nombre")
        telefono = request.form.get("telefono")
        direccion = request.form.get("direccion")
        mascota = request.form.get("mascota")

        conn = get_db_connection()
        cursor = conn.cursor()
        hashed_pw = generate_password_hash(password)

        cursor.execute("""
            INSERT INTO usuarios (email, password, rol, nombre, telefono, direccion, mascota)
            VALUES (%s, %s, 'cliente', %s, %s, %s, %s)
        """, (email, hashed_pw, nombre, telefono, direccion, mascota))

        conn.commit()
        cursor.close()
        conn.close()

        return redirect(url_for("login"))

    return render_template("registro.html")


# ------------------ MAIN ------------------
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
