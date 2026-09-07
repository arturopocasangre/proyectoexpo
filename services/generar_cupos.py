import pymysql
from pymysql.cursors import DictCursor
from datetime import datetime, timedelta, time

# -------------------
# Conexión directa a MySQL en Aiven
# -------------------
def get_db_connection():
    timeout = 10
    return pymysql.connect(
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

def convertir_a_time(valor):
    """Convierte un TIME de MySQL (timedelta) a datetime.time"""
    if isinstance(valor, timedelta):
        total_seconds = int(valor.total_seconds())
        horas = total_seconds // 3600
        minutos = (total_seconds % 3600) // 60
        segundos = total_seconds % 60
        return time(horas, minutos, segundos)
    elif isinstance(valor, time):
        return valor
    else:
        raise ValueError(f"Formato inesperado: {valor}")

def generar_cupos(inicio, fin):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        # Leer configuración desde la tabla (incluyendo precio)
        cursor.execute("SELECT * FROM configuracion_cupos")
        configuraciones = cursor.fetchall()

        fecha = inicio
        while fecha <= fin:
            dia_semana = fecha.weekday()  # 0=lunes, 6=domingo
            for conf in configuraciones:
                if conf["dia_semana"] == dia_semana:
                    hora_inicio = convertir_a_time(conf["hora_inicio"])
                    hora_fin = convertir_a_time(conf["hora_fin"])
                    intervalo = conf["intervalo"]
                    precio = conf["precio"]

                    hora_actual = datetime.combine(fecha, hora_inicio)
                    hora_limite = datetime.combine(fecha, hora_fin)

                    while hora_actual < hora_limite:
                        hora_str = hora_actual.strftime("%H:%M:%S")

                        # Verificar si ya existe cupo en esa fecha y hora
                        cursor.execute("""
                            SELECT COUNT(*) AS existe
                            FROM citas
                            WHERE fecha=%s AND hora=%s
                        """, (fecha, hora_str))
                        existe = cursor.fetchone()["existe"]

                        if existe == 0:
                            cursor.execute("""
                                INSERT INTO citas (fecha, hora, estado, precio)
                                VALUES (%s, %s, 'disponible', %s)
                            """, (fecha, hora_str, precio))

                        hora_actual += timedelta(minutes=intervalo)
            fecha += timedelta(days=1)

        conn.commit()
    conn.close()

def calcular_rango_semana():
    hoy = datetime.today().date()
    dias_hasta_lunes = (7 - hoy.weekday()) % 7
    inicio = hoy + timedelta(days=dias_hasta_lunes)
    fin = inicio + timedelta(days=6)# hasta domingo
    return inicio, fin

def generar_cupos_wrapper():
    inicio, fin = calcular_rango_semana()
    generar_cupos(inicio, fin)
    return f"Cupos generados para la semana {inicio} - {fin}"

if __name__ == "__main__":
    inicio, fin = calcular_rango_semana()
    generar_cupos(inicio, fin)
    print(f"Cupos generados para la semana {inicio} - {fin}")
