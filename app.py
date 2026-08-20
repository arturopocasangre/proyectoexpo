from flask import Flask, render_template, request, redirect, url_for, session
from flask import flash
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime, timedelta
import mysql.connector
import os
from pymysql.cursors import DictCursor
from collections import defaultdict
import stripe
import pymysql
import uuid
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import jsonify
from pymysql.err import IntegrityError # ASEGÚRATE DE PONER ESTA LÍNEA AL INICIO DE TU ARCHIVO APP.PY
# -------------------
# Inicializar Flask
# -------------------
app = Flask(__name__)
app.secret_key = "clave_secreta_segura"

# -------------------
# Conexión directa a MySQL en Aiven
# -------------------
def get_db_connection():
    timeout = 10
    conn = pymysql.connect(
        host="mysql-1bd38ea7-arturopocasangre-7e6b.e.aivencloud.com",  # Host de Aiven
        port=20045,                                                   # Puerto de Aiven
        user="avnadmin",                                              # Usuario
        password="AVNS_VZUcWWZw6qFpV1vTFf3",                          # Contraseña
        database="happy_paws_vet",                                    # Base de datos
        charset="utf8mb4",
        connect_timeout=timeout,
        read_timeout=timeout,
        write_timeout=timeout,
        cursorclass=DictCursor
    )

    #  hora local de El Salvador en cada conexión
    configurar_zona_horaria(conn)

    return conn

# -------------------
# configurar_zona_horaria
# -------------------
def configurar_zona_horaria(conn):
    cursor = conn.cursor()
    cursor.execute("SET time_zone = 'America/El_Salvador';")
    conn.commit()

    # Consultar la hora actual ajustada
    cursor.execute("SELECT NOW() AS hora_local;")
    hora_local = cursor.fetchone()

    # Acceder por clave del diccionario
    print(f"🌎 Zona horaria ajustada a America/El_Salvador → Hora actual: {hora_local['hora_local']}")

    cursor.close()


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

@app.route('/alimentos')
def alimentos():
    return render_template('alimentos.html')

@app.route('/accesorios')
def accesorios():
    return render_template('accesorios.html')

@app.route('/higiene')
def higiene():
    return render_template('higiene.html')

@app.route('/medicina')
def medicina():
    return render_template('medicina.html')

@app.route("/soporte")
def soporte():
    return render_template("soporte.html")

    # ============================================================
# LIMPIAR MENSAJE DEL PANEL ADMIN
# ============================================================
#
# Esta ruta se ejecuta cuando el administrador presiona OK.
# Su función es eliminar el mensaje guardado temporalmente
# en la sesión.
# ============================================================

@app.route("/limpiar-mensaje-admin", methods=["POST"])
def limpiar_mensaje_admin():

    # Eliminamos el mensaje de la sesión.
    session.pop("mensaje_admin", None)

    # No necesitamos devolver una página.
    return "", 204

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
# ============================================================
# AGREGAR UNA NUEVA CONFIGURACIÓN DE CUPO
# ============================================================
@app.route("/admin/configuracion/agregar", methods=["POST"])
def admin_configuracion_agregar():

    # --------------------------------------------------------
    # 1. OBTENEMOS LOS DATOS DEL FORMULARIO
    # --------------------------------------------------------
    #
    # Estos nombres vienen directamente de los inputs
    # que tenemos en admin_configuracion.html:
    #
    # dia_semana
    # hora_inicio
    # hora_fin
    # intervalo
    # precio
    # --------------------------------------------------------

    dia_semana = request.form["dia_semana"]

    hora_inicio = request.form["hora_inicio"]

    hora_fin = request.form["hora_fin"]

    intervalo = request.form["intervalo"]

    precio = request.form["precio"]


    # --------------------------------------------------------
    # 2. ABRIMOS LA CONEXIÓN CON LA BASE DE DATOS
    # --------------------------------------------------------

    conn = get_db_connection()


    # --------------------------------------------------------
    # 3. INSERTAMOS EL NUEVO CUPO
    # --------------------------------------------------------

    with conn.cursor() as cursor:

        cursor.execute("""
            INSERT INTO configuracion_cupos
            (
                dia_semana,
                hora_inicio,
                hora_fin,
                intervalo,
                precio
            )
            VALUES (%s, %s, %s, %s, %s)
        """, (
            dia_semana,
            hora_inicio,
            hora_fin,
            intervalo,
            precio
        ))


        # ----------------------------------------------------
        # 4. GUARDAMOS LOS CAMBIOS EN LA BASE DE DATOS
        # ----------------------------------------------------

        conn.commit()


    # --------------------------------------------------------
    # 5. CERRAMOS LA CONEXIÓN
    # --------------------------------------------------------

    conn.close()


    # --------------------------------------------------------
    # 6. GUARDAMOS EL MENSAJE PARA LA NOTIFICACIÓN
    # --------------------------------------------------------
    #
    # Este mensaje será leído posteriormente por
    # admin_configuracion.html.
    # --------------------------------------------------------

    session["mensaje_admin"] = (
        "El cupo se ha agregado correctamente."
    )


    # --------------------------------------------------------
    # 7. REGRESAMOS A LA PÁGINA DE CONFIGURACIÓN
    # --------------------------------------------------------
    #
    # Al regresar, el HTML verá el mensaje de la sesión
    # y mostrará la ventana emergente.
    # --------------------------------------------------------

    return redirect(
        url_for("admin_configuracion")
    )

# -------------------
# Eliminar configuración
# -------------------
# ============================================================
# ELIMINAR UNA CONFIGURACIÓN DE CUPO
# ============================================================
@app.route(
    "/admin/configuracion/eliminar/<int:id>",
    methods=["POST"]
)
def admin_configuracion_eliminar(id):

    # --------------------------------------------------------
    # 1. ABRIMOS LA CONEXIÓN CON LA BASE DE DATOS
    # --------------------------------------------------------

    conn = get_db_connection()


    # --------------------------------------------------------
    # 2. ELIMINAMOS EL CUPO SELECCIONADO
    # --------------------------------------------------------

    with conn.cursor() as cursor:

        cursor.execute(
            """
            DELETE FROM configuracion_cupos
            WHERE id=%s
            """,
            (id,)
        )


        # ----------------------------------------------------
        # 3. GUARDAMOS EL CAMBIO
        # ----------------------------------------------------

        conn.commit()


    # --------------------------------------------------------
    # 4. CERRAMOS LA CONEXIÓN
    # --------------------------------------------------------

    conn.close()


    # --------------------------------------------------------
    # 5. CREAMOS EL MENSAJE PARA EL ADMINISTRADOR
    # --------------------------------------------------------

    session["mensaje_admin"] = (
        "El cupo se ha eliminado correctamente."
    )


    # --------------------------------------------------------
    # 6. REGRESAMOS A LA CONFIGURACIÓN
    # --------------------------------------------------------

    return redirect(
        url_for("admin_configuracion")
    )

   

@app.route("/logout")
def logout():
    session.clear()  # elimina toda la información de la sesión
    return redirect(url_for("inicio"))

# -------------------
# Panel Admin
# -------------------
@app.route("/login", methods=["GET", "POST"])
def login():

    # ============================================================
    # Comprobamos si el usuario envió el formulario
    # ============================================================
    if request.method == "POST":

        # --------------------------------------------------------
        # Obtenemos correo y contraseña
        # --------------------------------------------------------
        email = request.form["email"]
        password = request.form["password"]


        # --------------------------------------------------------
        # Conectamos a la base de datos
        # --------------------------------------------------------
        conn = get_db_connection()


        # --------------------------------------------------------
        # Utilizamos DictCursor para poder acceder a los campos
        # de esta manera:
        #
        # usuario["password"]
        # usuario["rol"]
        # usuario["id"]
        # --------------------------------------------------------
        cursor = conn.cursor(DictCursor)


        # --------------------------------------------------------
        # Buscamos el usuario por correo.
        #
        # activo=1 significa que solamente buscamos usuarios
        # activos.
        # --------------------------------------------------------
        cursor.execute(
            "SELECT * FROM usuarios WHERE email=%s and activo=1",
            (email,)
        )


        # --------------------------------------------------------
        # Guardamos el resultado
        # --------------------------------------------------------
        usuario = cursor.fetchone()


        # --------------------------------------------------------
        # Cerramos la conexión
        # --------------------------------------------------------
        cursor.close()
        conn.close()


        # ========================================================
        # COMPROBAMOS CORREO Y CONTRASEÑA
        # ========================================================

        if usuario and check_password_hash(
            usuario["password"],
            password
        ):

            # ----------------------------------------------------
            # Si los datos son correctos,
            # guardamos la sesión.
            # ----------------------------------------------------
            session["usuario_id"] = usuario["id"]
            session["rol"] = usuario["rol"]


            # ====================================================
            # REDIRECCIÓN NORMAL CUANDO EL LOGIN ES CORRECTO
            # ====================================================

            if usuario["rol"] == "admin":

                return redirect(
                    url_for("panel_admin")
                )


            elif usuario["rol"] == "veterinario":

                return redirect(
                    url_for("panel_veterinario")
                )


            else:

                return redirect(
                    url_for("panel_cliente")
                )


        else:

            # ====================================================
            # LOGIN INCORRECTO
            # ====================================================

            # ----------------------------------------------------
            # Guardamos el mensaje temporalmente.
            # ----------------------------------------------------
            flash(
                "El correo electrónico o la contraseña son incorrectos.",
                "error"
            )


            # ----------------------------------------------------
            # REGRESAMOS AL MISMO LOGIN
            # ----------------------------------------------------
            return redirect(
                url_for("login")
            )


    # ============================================================
    # MOSTRAMOS EL LOGIN
    # ============================================================

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

        # Traer citas confirmadas del cliente
        cursor.execute("""
            SELECT id, fecha, hora, estado, link_consulta
            FROM citas
            WHERE cliente_id=%s
            AND estado = 'pagada'
            AND TIMESTAMP(fecha, hora) > (NOW() - INTERVAL 1 HOUR)
            ORDER BY fecha, hora
        """, (usuario_id,))
        citas = cursor.fetchall()

        # Traer cupos disponibles
        cursor.execute("""
            SELECT * 
            FROM citas 
            WHERE estado='disponible' and cliente_id is null
            AND TIMESTAMP(fecha, hora) > (NOW() + INTERVAL 1 HOUR)
            ORDER BY fecha, hora
        """)
        cupos = cursor.fetchall()
        
        # Traer citas pasadas (pagadas pero ya vencidas)
        cursor.execute("""
            SELECT * 
            FROM citas 
            WHERE cliente_id=%s 
              AND estado='pagada' 
              AND TIMESTAMP(fecha, hora) < (NOW() - INTERVAL 1 HOUR) 
            ORDER BY fecha, hora
        """, (usuario_id,))
        vencidas = cursor.fetchall()

    conn.close()

    for cita in citas:
        fecha_hora = datetime.strptime(f"{cita['fecha']} {cita['hora']}", "%Y-%m-%d %H:%M:%S")
        # Obtener la hora actual desde MySQL
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT NOW() AS ahora;")
            resultado = cursor.fetchone()
            ahora = resultado["ahora"]  # viene como datetime naive en zona local
        conn.close()
    
        # habilitar desde 10 minutos antes hasta 30 minutos después
        inicio = fecha_hora - timedelta(minutes=10)
        fin = fecha_hora + timedelta(minutes=30)
        cita["habilitar"] = (inicio <= ahora <= fin)
        
    # 🔹 Imprimir en consola para depuración
        print("📌 Cita ID:", cita["id"])
        print("   Fecha/Hora cita:", fecha_hora)
        print("   Hora actual:", ahora)
        print("   Inicio habilitación:", inicio)
        print("   Fin habilitación:", fin)
        print("   ¿Habilitada?:", cita["habilitar"])
        print("-" * 50)


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
# ============================================================
# CREAR NUEVO USUARIO DESDE EL PANEL DE ADMINISTRADOR
# ============================================================

@app.route("/admin/usuario/nuevo", methods=["GET", "POST"])
def nuevo_usuario():

    # --------------------------------------------------------
    # 1. COMPROBAMOS QUE EL USUARIO SEA ADMINISTRADOR
    # --------------------------------------------------------

    if session.get("rol") != "admin":
        return "Acceso denegado"


    # --------------------------------------------------------
    # 2. COMPROBAMOS SI SE ENVIÓ EL FORMULARIO
    # --------------------------------------------------------

    if request.method == "POST":


        # ====================================================
        # 3. OBTENER LOS DATOS DEL FORMULARIO
        # ====================================================

        # Correo electrónico.
        email = request.form["email"]


        # Contraseña.
        password = request.form["password"]


        # Rol seleccionado.
        rol = request.form["rol"]


        # Estado del usuario.
        activo = request.form["activo"]


        # Nombre completo.
        nombre = request.form["nombre"]


        # Teléfono.
        telefono = request.form["telefono"]


        # Dirección.
        direccion = request.form["direccion"]


        # ====================================================
        # 4. ENCRIPTAR LA CONTRASEÑA
        # ====================================================
        #
        # Nunca guardamos la contraseña directamente en MySQL.
        # La convertimos en un hash.
        # ====================================================

        hashed_pw = generate_password_hash(
            password
        )


        # ====================================================
        # 5. CONECTARNOS A LA BASE DE DATOS
        # ====================================================

        conn = get_db_connection()


        # ====================================================
        # 6. INSERTAR EL NUEVO USUARIO
        # ====================================================

        with conn.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO usuarios
                (
                    email,
                    password,
                    rol,
                    activo,
                    nombre,
                    telefono,
                    direccion
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    email,
                    hashed_pw,
                    rol,
                    activo,
                    nombre,
                    telefono,
                    direccion
                )
            )


            # ------------------------------------------------
            # 7. GUARDAR LOS CAMBIOS
            # ------------------------------------------------

            conn.commit()


        # ====================================================
        # 8. CERRAR LA CONEXIÓN
        # ====================================================

        conn.close()


        # ====================================================
        # 9. CREAR EL MENSAJE DE CONFIRMACIÓN
        # ====================================================
        #
        # Este mensaje queda temporalmente guardado en la
        # sesión.
        #
        # Cuando volvamos al panel_admin, nuestro HTML
        # detectará este mensaje y mostrará la ventana.
        # ====================================================

        session["mensaje_admin"] = (
            "El usuario se ha creado correctamente."
        )


        # ====================================================
        # 10. REGRESAR AL PANEL DE ADMINISTRACIÓN
        # ====================================================

        return redirect(
            url_for("panel_admin")
        )


    # ========================================================
    # 11. SI ES GET
    # ========================================================
    #
    # Cuando presionamos "+ Nuevo Usuario", todavía no existe
    # ningún usuario para editar.
    #
    # Por eso enviamos:
    #
    # usuario=None
    #
    # Esto hace que nuestro usuario_form.html muestre:
    #
    #       Crear Usuario
    #
    # en lugar de:
    #
    #       Editar Usuario
    # ========================================================

    return render_template(
        "usuario_form.html",
        usuario=None
    )
# ============================================================
# EDITAR USUARIO DESDE EL PANEL DE ADMINISTRADOR
# ============================================================
#
# Esta ruta permite al administrador:
#
# - Ver los datos actuales de un usuario.
# - Cambiar su correo.
# - Cambiar su contraseña.
# - Cambiar su rol.
# - Activar o desactivar el usuario.
# - Cambiar nombre.
# - Cambiar teléfono.
# - Cambiar dirección.
#
# Cuando la modificación se realiza correctamente,
# guardamos un mensaje en la sesión para que aparezca
# nuestra ventana emergente de confirmación.
# ============================================================

# ============================================================
# EDITAR USUARIO DESDE EL PANEL DE ADMINISTRADOR
# ============================================================
#
# Esta ruta permite al administrador:
#
# - Ver los datos actuales de un usuario.
# - Cambiar su correo.
# - Cambiar su contraseña.
# - Cambiar su rol.
# - Activar o desactivar el usuario.
# - Cambiar nombre.
# - Cambiar teléfono.
# - Cambiar dirección.
#
# Cuando la modificación se realiza correctamente,
# guardamos un mensaje en la sesión para que aparezca
# nuestra ventana emergente de confirmación.
# ============================================================

@app.route(
    "/admin/usuario/editar/<int:usuario_id>",
    methods=["GET", "POST"]
)
def editar_usuario(usuario_id):

    # ========================================================
    # 1. VERIFICAR QUE QUIEN ESTÁ ACCEDIENDO SEA ADMIN
    # ========================================================

    if session.get("rol") != "admin":

        # Si no es administrador, no permitimos el acceso.
        return "Acceso denegado"


    # ========================================================
    # 2. CONECTAR CON LA BASE DE DATOS
    # ========================================================

    conn = get_db_connection()


    # ========================================================
    # 3. BUSCAR EL USUARIO QUE SE QUIERE EDITAR
    # ========================================================

    with conn.cursor() as cursor:

        cursor.execute(
            """
            SELECT *
            FROM usuarios
            WHERE id=%s
            """,
            (usuario_id,)
        )

        # Guardamos los datos encontrados.
        usuario = cursor.fetchone()


    # ========================================================
    # 4. COMPROBAR SI EL FORMULARIO FUE ENVIADO
    # ========================================================

    if request.method == "POST":


        # ====================================================
        # 5. OBTENER LOS DATOS DEL FORMULARIO
        # ====================================================

        # Correo electrónico.
        email = request.form["email"]


        # Contraseña.
        #
        # Usamos .get() porque puede venir vacía.
        #
        # Si viene vacía significa que el administrador
        # NO quiere cambiar la contraseña actual.
        password = request.form.get("password")


        # Rol del usuario.
        rol = request.form["rol"]


        # Estado del usuario.
        #
        # Puede ser activo o inactivo dependiendo
        # de cómo tengas construido tu formulario.
        activo = request.form.get("activo")


        # Nombre completo.
        nombre = request.form.get("nombre")


        # Teléfono.
        telefono = request.form.get("telefono")


        # Dirección.
        direccion = request.form.get("direccion")


        # ====================================================
        # 6. ABRIR CURSOR PARA ACTUALIZAR EL USUARIO
        # ====================================================

        with conn.cursor() as cursor:


            # =================================================
            # 7. COMPROBAR SI EL ADMINISTRADOR CAMBIÓ
            #    LA CONTRASEÑA
            # =================================================

            if password:


                # ------------------------------------------------
                # Si escribió una contraseña nueva,
                # NO debemos guardarla directamente.
                #
                # Primero la convertimos en un hash seguro.
                # ------------------------------------------------

                hashed_pw = generate_password_hash(
                    password
                )


                # ------------------------------------------------
                # Actualizamos todos los datos incluyendo
                # la nueva contraseña.
                # ------------------------------------------------

                cursor.execute(
                    """
                    UPDATE usuarios

                    SET
                        email=%s,
                        password=%s,
                        rol=%s,
                        activo=%s,
                        nombre=%s,
                        telefono=%s,
                        direccion=%s

                    WHERE id=%s
                    """,
                    (
                        email,
                        hashed_pw,
                        rol,
                        activo,
                        nombre,
                        telefono,
                        direccion,
                        usuario_id
                    )
                )


            else:


                # =================================================
                # 8. SI NO ESCRIBIÓ CONTRASEÑA
                # =================================================
                #
                # En este caso conservamos la contraseña
                # que el usuario ya tenía.
                # =================================================

                cursor.execute(
                    """
                    UPDATE usuarios

                    SET
                        email=%s,
                        rol=%s,
                        activo=%s,
                        nombre=%s,
                        telefono=%s,
                        direccion=%s

                    WHERE id=%s
                    """,
                    (
                        email,
                        rol,
                        activo,
                        nombre,
                        telefono,
                        direccion,
                        usuario_id
                    )
                )


            # =================================================
            # 9. GUARDAR LOS CAMBIOS EN LA BASE DE DATOS
            # =================================================

            conn.commit()


        # ====================================================
        # 10. CERRAR LA CONEXIÓN
        # ====================================================

        conn.close()


        # ====================================================
        # 11. CREAR LA NOTIFICACIÓN
        # ====================================================
        #
        # Aquí está el cambio que estamos haciendo.
        #
        # Guardamos temporalmente este mensaje en la sesión.
        #
        # admin.html lo va a detectar y mostrará nuestra
        # ventana emergente.
        # ====================================================

        session["mensaje_admin"] = (
            "Los datos del usuario se han actualizado correctamente."
        )


        # ====================================================
        # 12. REGRESAR AL PANEL DE ADMINISTRADOR
        # ====================================================
        #
        # Después de guardar los cambios regresamos al panel.
        #
        # Como el mensaje está en session, el panel podrá
        # mostrar la notificación.
        # ====================================================

        return redirect(
            url_for("panel_admin")
        )


    # ========================================================
    # 13. SI ES GET
    # ========================================================
    #
    # Significa que simplemente estamos entrando al formulario
    # para ver/editar los datos del usuario.
    # ========================================================

    conn.close()


    # ========================================================
    # 14. MOSTRAR EL FORMULARIO DE EDICIÓN
    # ========================================================

    return render_template(
        "usuario_form.html",
        usuario=usuario
    )
# ============================================================
# CREAR NUEVO CUPO / CITA DESDE EL PANEL DE ADMINISTRADOR
# ============================================================

@app.route("/admin/cita/nueva", methods=["GET", "POST"])
def nueva_cita():

    # --------------------------------------------------------
    # 1. VERIFICAR QUE EL USUARIO SEA ADMINISTRADOR
    # --------------------------------------------------------

    if session.get("rol") != "admin":

        # Si no es administrador, no permitimos el acceso.
        return "Acceso denegado"


    # --------------------------------------------------------
    # 2. COMPROBAR SI SE ENVIÓ EL FORMULARIO
    # --------------------------------------------------------

    if request.method == "POST":


        # ====================================================
        # 3. OBTENER LOS DATOS DEL FORMULARIO
        # ====================================================

        # Fecha en la que estará disponible el cupo.
        fecha = request.form["fecha"]


        # Hora del cupo.
        hora = request.form["hora"]


        # Precio de la cita.
        precio = request.form["precio"]


        # Cliente seleccionado.
        #
        # Si el administrador no selecciona ningún cliente,
        # guardaremos None, que en MySQL corresponde a NULL.
        cliente = request.form.get("cliente") or None


        # Estado inicial de la cita/cupo.
        estado = request.form["estado"]


        # ====================================================
        # 4. CONECTAR CON LA BASE DE DATOS
        # ====================================================

        conn = get_db_connection()


        # ====================================================
        # 5. INSERTAR EL NUEVO CUPO
        # ====================================================

        with conn.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO citas
                (
                    fecha,
                    hora,
                    precio,
                    cliente_id,
                    estado
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    fecha,
                    hora,
                    precio,
                    cliente,
                    estado
                )
            )


            # ------------------------------------------------
            # 6. GUARDAR LOS CAMBIOS
            # ------------------------------------------------

            conn.commit()


        # ====================================================
        # 7. CERRAR LA CONEXIÓN
        # ====================================================

        conn.close()


        # ====================================================
        # 8. CREAR LA NOTIFICACIÓN
        # ====================================================
        #
        # Esta variable será detectada por nuestro
        # panel_admin.html.
        #
        # Como el panel ya tiene la ventana emergente,
        # no necesitamos crear otro HTML ni otro CSS.
        # ====================================================

        session["mensaje_admin"] = (
            "El cupo se ha creado correctamente."
        )


        # ====================================================
        # 9. REGRESAR AL PANEL DE ADMINISTRACIÓN
        # ====================================================

        return redirect(
            url_for("panel_admin")
        )


    # ========================================================
    # 10. SI ES GET, TRAEMOS LOS CLIENTES
    # ========================================================
    #
    # Esto ocurre cuando simplemente presionamos:
    #
    #       + Crear Cupo
    #
    # y necesitamos mostrar el formulario.
    # ========================================================

    conn = get_db_connection()


    with conn.cursor() as cursor:


        # ----------------------------------------------------
        # Buscamos únicamente los usuarios cuyo rol sea
        # "cliente".
        # ----------------------------------------------------

        cursor.execute(
            """
            SELECT *
            FROM usuarios
            WHERE rol='cliente'
            """
        )


        # Guardamos todos los clientes encontrados.
        clientes = cursor.fetchall()


    # Cerramos la conexión.
    conn.close()


    # ========================================================
    # 11. MOSTRAR EL FORMULARIO
    # ========================================================
    #
    # Como estamos creando una nueva cita,
    # no existe todavía una cita específica.
    #
    # Por eso enviamos:
    #
    #       cita=None
    #
    # El formulario cita_form.html puede utilizar esto
    # para saber que estamos creando.
    # ========================================================

    return render_template(
        "cita_form.html",
        cita=None,
        clientes=clientes
    )
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

    # ============================================================
    # Si el usuario envió el formulario
    # ============================================================
    if request.method == "POST":

        # --------------------------------------------------------
        # Obtenemos los datos enviados desde registro.html
        # --------------------------------------------------------
        email = request.form["email"]
        password = request.form["password"]
        nombre = request.form.get("nombre")
        telefono = request.form.get("telefono")
        direccion = request.form.get("direccion")
        mascota = request.form.get("mascota")


        # --------------------------------------------------------
        # Conectamos con la base de datos
        # --------------------------------------------------------
        conn = get_db_connection()
        cursor = conn.cursor()


        # --------------------------------------------------------
        # Encriptamos la contraseña antes de guardarla
        # --------------------------------------------------------
        hashed_pw = generate_password_hash(password)


        try:

            # ====================================================
            # INTENTAMOS CREAR EL USUARIO
            # ====================================================

            cursor.execute("""
                INSERT INTO usuarios
                (email, password, rol, nombre, telefono, direccion, mascota)
                VALUES (%s, %s, 'cliente', %s, %s, %s, %s)
            """, (
                email,
                hashed_pw,
                nombre,
                telefono,
                direccion,
                mascota
            ))


            # ----------------------------------------------------
            # Confirmamos los cambios
            # ----------------------------------------------------
            conn.commit()


            # ----------------------------------------------------
            # Cerramos conexión
            # ----------------------------------------------------
            cursor.close()
            conn.close()


            # ----------------------------------------------------
            # Si todo salió bien:
            #
            # enviamos al usuario al login.
            # ----------------------------------------------------
            return redirect(url_for("login"))


        except IntegrityError as e:

            # ====================================================
            # HUBO UN ERROR AL INSERTAR
            # ====================================================

            # Cerramos las conexiones
            cursor.close()
            conn.close()


            # ----------------------------------------------------
            # Error 1062 = dato duplicado
            #
            # En nuestro caso normalmente será porque el correo
            # ya existe.
            # ----------------------------------------------------
            if e.args[0] == 1062:

                # ------------------------------------------------
                # En lugar de mostrar una página nueva con el
                # mensaje, guardamos el mensaje temporalmente.
                # ------------------------------------------------
                flash(
                    "El correo electrónico ya está registrado. Por favor, intenta con otro.",
                    "error"
                )


                # ------------------------------------------------
                # Regresamos al MISMO formulario de registro.
                # ------------------------------------------------
                return redirect(url_for("registro"))


            # ----------------------------------------------------
            # Si fue otro error de base de datos
            # ----------------------------------------------------
            flash(
                "Ocurrió un error al intentar registrar la cuenta.",
                "error"
            )


            # ----------------------------------------------------
            # También regresamos al registro.
            # ----------------------------------------------------
            return redirect(url_for("registro"))

    # ============================================================
    # Si simplemente entramos a /registro mediante GET
    # ============================================================

    return render_template("registro.html")


    # ============================================================
    # Si simplemente entramos a /registro mediante GET
    # ============================================================

# ============================================================
# aplicación Flask instalable en el celular como PWA
# ============================================================
@app.route('/manifest.json')
def manifest():
    return app.send_static_file('manifest.json')

@app.route('/service-worker.js')
def sw():
    return app.send_static_file('service-worker.js')

# ============================================================
# ############
# ============================================================
# ------------------ MAIN ------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    try:
        conn = get_db_connection()
        conn.close()
    except Exception as e:
        import traceback
        print("⚠️ No se pudo conectar a MySQL:")
        traceback.print_exc()   # imprime el error completo en consola

    app.run(debug=True, host="0.0.0.0", port=port)
