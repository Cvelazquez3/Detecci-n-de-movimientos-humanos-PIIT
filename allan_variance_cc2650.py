"""
Calculo de la Varianza de Allan (Allan Variance) para la captura de 4 horas
del SensorTag CC2650STK (archivo Prueba_4_horas.csv), comparando muestra
por muestra (tau en unidades ENTERAS de muestras, no en segundos).

El CSV tiene 6 columnas, sin timestamp, una fila = una muestra:
    acc_x, acc_y, acc_z, gyr_x, gyr_y, gyr_z

Requisitos:
    pip install pandas numpy matplotlib allantools

Uso basico:
    # Analiza las 6 columnas y muestra una grafica con 6 subplots
    python allan_variance_cc2650.py Prueba_4_horas.csv

    # Analiza solo columnas especificas (separadas por coma)
    python allan_variance_cc2650.py Prueba_4_horas.csv --columnas acc_x,acc_y,acc_z

    # Guardar la grafica como imagen
    python allan_variance_cc2650.py Prueba_4_horas.csv --salida resultado.png

    # Resolucion completa (todos los tau enteros: 1,2,3,4,...), mas lento
    python allan_variance_cc2650.py Prueba_4_horas.csv --resolucion all
"""

import argparse
import sys

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import allantools

COLUMNAS_DEFAULT = ["acc_x", "acc_y", "acc_z", "gyr_x", "gyr_y", "gyr_z"]


def cargar_datos(ruta_csv):
    return pd.read_csv(ruta_csv)


def calcular_allan_varianza(serie, resolucion="octave"):
    """
    Calcula la Varianza de Allan usando allantools, comparando MUESTRA POR
    MUESTRA: rate=1.0 hace que tau se exprese en numero entero de muestras
    (1, 2, 3, 4, ...) en lugar de segundos.

    resolucion:
        "all"    -> evalua tau = 1, 2, 3, 4, 5, ... (todos los enteros).
                    Mas preciso pero mas lento (126475 muestras en total).
        "octave" -> evalua tau = 1, 2, 4, 8, 16, ... (potencias de 2).
                    Rapido, recomendado como primer analisis.
    """
    datos = np.asarray(serie, dtype=float)
    datos = datos[~np.isnan(datos)]

    taus_arg = "all" if resolucion == "all" else "octave"

    # oadev = Overlapping Allan Deviation (mejor aprovechamiento estadistico
    # de los datos que la version no solapada). data_type="freq" trata cada
    # muestra como un valor instantaneo de la señal (caso de acc/gyro ya
    # muestreados en el tiempo).
    tau, adev, adev_err, n = allantools.oadev(
        datos, rate=1.0, data_type="freq", taus=taus_arg
    )

    avar = adev ** 2                 # Varianza de Allan = (Desv. de Allan)^2
    avar_err = 2 * adev * adev_err   # propagacion de error aproximada

    return tau, avar, avar_err, n


def graficar_todas(resultados, salida=None):
    """
    resultados: dict {nombre_columna: (tau, avar)}
    Dibuja una cuadricula de subplots log-log, uno por columna.
    """
    n_cols = len(resultados)
    filas = 2 if n_cols > 1 else 1
    cols = int(np.ceil(n_cols / filas)) if n_cols > 1 else 1

    fig, axes = plt.subplots(filas, cols, figsize=(6 * cols, 5 * filas))
    axes = np.atleast_1d(axes).flatten()

    for ax, (nombre, (tau, avar)) in zip(axes, resultados.items()):
        ax.loglog(tau, avar, marker="o", linestyle="-", markersize=4)
        ax.set_xlabel("Tau (numero entero de muestras)")
        ax.set_ylabel("Varianza de Allan")
        ax.set_title(nombre)
        ax.grid(True, which="both", linestyle="--", alpha=0.6)

    # Ocultar ejes sobrantes si el grid es mas grande que el numero de columnas
    for ax in axes[len(resultados):]:
        ax.axis("off")

    fig.suptitle("Varianza de Allan - CC2650STK (comparacion muestra a muestra)")
    fig.tight_layout()

    if salida:
        fig.savefig(salida, dpi=150)
        print(f"\nGrafica guardada en: {salida}")

    plt.show()


def main():
    parser = argparse.ArgumentParser(
        description="Calcula y grafica la Varianza de Allan (muestra por "
                     "muestra, tau entero) para la captura del CC2650STK."
    )
    parser.add_argument("csv", help="C:\\Users\\LEGION\\Downloads\\PIIT PROYECT\\Detecci-n-de-movimientos-humanos-PIIT\\Prueba_4 horas.csv")
    parser.add_argument(
        "--columnas", default=None,
        help="Columnas a analizar, separadas por coma (ej: acc_x,gyr_z). "
             f"Por defecto se analizan todas: {','.join(COLUMNAS_DEFAULT)}"
    )
    parser.add_argument(
        "--resolucion", default="octave", choices=["all", "octave"],
        help="'all' evalua todos los tau enteros; 'octave' usa potencias "
             "de 2 (mas rapido). Default: octave."
    )
    parser.add_argument(
        "--salida", default=None,
        help="Ruta para guardar la grafica combinada como imagen (opcional)."
    )
    args = parser.parse_args()

    df = cargar_datos(args.csv)

    if args.columnas:
        columnas = [c.strip() for c in args.columnas.split(",")]
    else:
        columnas = COLUMNAS_DEFAULT

    faltantes = [c for c in columnas if c not in df.columns]
    if faltantes:
        print(f"Error: estas columnas no existen en el CSV: {faltantes}")
        print("Columnas disponibles:", list(df.columns))
        sys.exit(1)

    resultados = {}
    for col in columnas:
        print(f"\nCalculando Varianza de Allan para '{col}'...")
        tau, avar, avar_err, n = calcular_allan_varianza(
            df[col], resolucion=args.resolucion
        )
        resultados[col] = (tau, avar)

        print(f"{'Tau (muestras)':>15} | {'Varianza Allan':>16} | {'Error':>12} | {'N usados':>9}")
        for t, a, e, ni in zip(tau, avar, avar_err, n):
            print(f"{int(t):>15} | {a:>16.6e} | {e:>12.6e} | {ni:>9}")

    graficar_todas(resultados, salida=args.salida)


if __name__ == "__main__":
    main()
