import argparse
import asyncio
import time
import pandas as pd
from bleak import BleakClient, BleakScanner

MOV_DATA = "f000aa81-0451-4000-b000-000000000000"
MOV_CONF = "f000aa82-0451-4000-b000-000000000000"
MOV_PERI = "f000aa83-0451-4000-b000-000000000000"

# ---------------------------------------------------------------------------
# Frecuencias de muestreo soportadas
# ---------------------------------------------------------------------------
# El registro MOV_PERI (periodo del sensor de movimiento) del CC2650 SensorTag
# tiene, segun la documentacion oficial de TI, una resolucion de 10ms y un
# RANGO DOCUMENTADO de 100ms (0x0A) a 2.55s (0xFF). Es decir, 10Hz es la
# frecuencia MAXIMA soportada por el firmware de fabrica; no es una eleccion
# arbitraria. Pedir 50Hz (periodo de 20ms) esta FUERA de ese rango: el
# firmware de fabrica puede ignorar el valor y quedarse en 10Hz, o truncarlo
# al minimo permitido. Por eso el script SIEMPRE mide la frecuencia real
# lograda a partir de los timestamps de llegada de los paquetes BLE, y te
# avisa si no coincide con lo solicitado. No asumas que "pediste 50Hz" es
# lo mismo que "tienes datos a 50Hz": confia en el valor medido, no en el
# valor solicitado.
FRECUENCIAS_SOPORTADAS = {
    10: 0x0A,  # 10 * 10ms = 100ms  -> dentro del rango documentado por TI
    50: 0x02,  #  2 * 10ms =  20ms  -> FUERA del rango documentado por TI
}

TOLERANCIA_FS_HZ = 1.0  # diferencia maxima aceptable entre Fs pedida y medida antes de avisar

N_CALIBRACION_SEGUNDOS = 3  # duracion fija de la fase de calibracion, en segundos (independiente de Fs)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Graba datos crudos del TI SensorTag CC2650 (IMU MPU-9250) via BLE."
    )
    parser.add_argument(
        "--freq", type=int, choices=sorted(FRECUENCIAS_SOPORTADAS.keys()), default=10,
        help="Frecuencia de muestreo solicitada al SensorTag, en Hz (default: 10)."
    )
    parser.add_argument(
        "--horas", type=float, default=8.0,
        help="Duracion de la fase de grabacion en horas (default: 8)."
    )
    parser.add_argument(
        "--salida", type=str, default=None,
        help="Nombre del archivo CSV de salida (default: Grabacion_<freq>Hz.csv)."
    )
    return parser.parse_args()


datos = []


def callback_sensores(sender, raw, n_calibracion, n_muestras, fs_objetivo):
    global datos
    if len(raw) < 12:
        return

    # Giroscopio en rad/s (compatible con MobiFall)
    gx = int.from_bytes(raw[0:2], "little", signed=True) * 0.00875 / 57.2958
    gy = int.from_bytes(raw[2:4], "little", signed=True) * 0.00875 / 57.2958
    gz = int.from_bytes(raw[4:6], "little", signed=True) * 0.00875 / 57.2958

    # Acelerometro en g
    ax = int.from_bytes(raw[6:8],  "little", signed=True) / 16384.0
    ay = int.from_bytes(raw[8:10], "little", signed=True) / 16384.0
    az = int.from_bytes(raw[10:12], "little", signed=True) / 16384.0

    datos.append({
        'timestamp': time.time(),
        'acc_x': ax, 'acc_y': ay, 'acc_z': az,
        'gyr_x': gx, 'gyr_y': gy, 'gyr_z': gz
    })

    n = len(datos)

    if n <= n_calibracion:
        restantes = n_calibracion - n
        barra = "█" * (n_calibracion - restantes) + "░" * restantes
        print(f"\r  [{barra}] Calibrando... {restantes} muestras restantes", end="", flush=True)
        if n == n_calibracion:
            print(f"\n  Calibracion lista. REALIZA EL MOVIMIENTO AHORA.")
    else:
        muestras_movimiento = n - n_calibracion
        total_movimiento    = n_muestras - n_calibracion
        muestras_restantes  = n_muestras - n
        segundos_restantes  = muestras_restantes / fs_objetivo
        horas = int(segundos_restantes // 3600)
        minutos = int((segundos_restantes % 3600) // 60)
        segundos = int(segundos_restantes % 60)
        print(f"\r  Grabando: {muestras_movimiento}/{total_movimiento} muestras | Tiempo restante: {horas:02d}:{minutos:02d}:{segundos:02d}", end="", flush=True)


async def grabar(freq_hz, horas, nombre_archivo):
    global datos
    datos = []

    n_calibracion = N_CALIBRACION_SEGUNDOS * freq_hz
    n_muestras = int(horas * 3600 * freq_hz) + n_calibracion
    period_byte = FRECUENCIAS_SOPORTADAS[freq_hz]

    print("Buscando SensorTag...")
    device = None
    detected = await BleakScanner.discover(timeout=5.0)
    for d in detected:
        if d.name and "SensorTag" in d.name:
            device = d
            break

    if not device:
        print("Error: No se encontro el SensorTag.")
        return

    try:
        async with BleakClient(device) as client:
            print(f"Conectado a {device.address}. Configurando a {freq_hz}Hz (periodo solicitado: {period_byte * 10}ms)...")

            if freq_hz not in (10,):
                print(f"  AVISO: {freq_hz}Hz esta fuera del rango de periodo documentado por TI (100ms-2.55s).")
                print(f"  El SensorTag puede ignorar esta configuracion y quedarse en 10Hz. Se medira la Fs real.")

            await client.write_gatt_char(MOV_PERI, bytearray([period_byte]))
            await client.write_gatt_char(MOV_CONF, bytearray([0x3F, 0x00]))
            await asyncio.sleep(1.5)

            def _cb(sender, raw):
                callback_sensores(sender, raw, n_calibracion, n_muestras, freq_hz)

            await client.start_notify(MOV_DATA, _cb)

            print(f"\n{'='*50}")
            print(f"  FASE 1 — CALIBRACION ({N_CALIBRACION_SEGUNDOS} segundos)")
            print(f"  Coloca el sensor en la cintura y queda COMPLETAMENTE QUIETO.")
            print(f"  No te muevas hasta que aparezca 'REALIZA EL MOVIMIENTO AHORA'")
            print(f"{'='*50}")

            # Esperar calibracion
            while len(datos) < n_calibracion:
                await asyncio.sleep(0.1)

            # --- Verificacion temprana de la frecuencia real lograda ---
            if len(datos) >= 2:
                dt_calib = datos[-1]['timestamp'] - datos[0]['timestamp']
                fs_calib = (len(datos) - 1) / dt_calib if dt_calib > 0 else 0
                print(f"\n  Frecuencia real medida durante calibracion: {fs_calib:.2f} Hz (solicitada: {freq_hz} Hz)")
                if abs(fs_calib - freq_hz) > TOLERANCIA_FS_HZ:
                    print(f"  *** AVISO: la Fs real NO coincide con la solicitada. El SensorTag probablemente")
                    print(f"  *** esta limitado a 10Hz por firmware de fabrica. Revisa el CSV final con cuidado.")

            print(f"\n{'='*50}")
            print(f"  FASE 2 — GRABACION DE MOVIMIENTO ({(n_muestras - n_calibracion) / freq_hz:.0f} segundos objetivo)")
            print(f"  Camina 3-4 pasos y realiza la caida sobre la colchoneta.")
            print(f"  Queda en el suelo hasta que aparezca 'Archivo guardado'.")
            print(f"{'='*50}\n")

            # Esperar grabacion completa
            while len(datos) < n_muestras:
                await asyncio.sleep(0.1)

            await client.stop_notify(MOV_DATA)

            df = pd.DataFrame(datos)
            duracion = df['timestamp'].iloc[-1] - df['timestamp'].iloc[0]
            fs_real  = (len(df) - 1) / duracion if duracion > 0 else 0
            print(f"\nFrecuencia real (grabacion completa): {fs_real:.2f} Hz (solicitada: {freq_hz} Hz)")
            if abs(fs_real - freq_hz) > TOLERANCIA_FS_HZ:
                print(f"AVISO: la Fs real medida difiere de la solicitada en mas de {TOLERANCIA_FS_HZ}Hz.")
                print(f"Verifica el firmware del SensorTag si necesitas {freq_hz}Hz de forma confiable.")

            # Guardar sin timestamp, columnas ordenadas por eje (datos crudos del sensor)
            columnas = ['acc_x', 'acc_y', 'acc_z', 'gyr_x', 'gyr_y', 'gyr_z']
            df[columnas].to_csv(nombre_archivo, index=False)
            print(f"\nArchivo guardado: {nombre_archivo}")
            print(f"Duracion total: {duracion:.1f} segundos")
            print(f"Fs solicitada: {freq_hz} Hz | Fs real medida: {fs_real:.2f} Hz")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    args = parse_args()
    salida = args.salida or f"Grabacion_{args.freq}Hz.csv"
    asyncio.run(grabar(args.freq, args.horas, salida))