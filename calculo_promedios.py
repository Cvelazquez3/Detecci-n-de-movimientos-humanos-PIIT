import os
import glob
import pandas as pd
import numpy as np

G = np.array([
        [1, -1,  0,  0,  0,  0],
        [0,  0,  1, -1,  0,  0],
        [0,  0,  0,  0,  1, -1]
    ], dtype=float) # Definida como float por si requieres operaciones con decimales después

def ejecutar_pipeline_completo(carpeta_origen=r"C:\Proyecto IMU´S PIIT\Pruebas semana II\10Hz)", archivo_csv_intermedio="Promedios.csv"):
    print("======================================================================")
    print("INICIANDO PIPELINE AUTOMATIZADO DE PROCESAMIENTO MATRICIAL")
    print("======================================================================\n")
    
    # ------------------------------------------------------------------------
    # PASO 1: Procesar los archivos de muestreo y calcular promedios
    # ------------------------------------------------------------------------
    archivos_csv = glob.glob(os.path.join(carpeta_origen, "*.csv"))
    archivos_a_procesar = [f for f in archivos_csv if os.path.basename(f) != archivo_csv_intermedio]
    
    if not archivos_a_procesar:
        print(f"Error: No se encontraron archivos CSV para procesar en: {carpeta_origen}")
        return None
        
    print(f"1. Leyendo {len(archivos_a_procesar)} archivos de muestreo...")
    matriz_resumen = []
    
    for idx, ruta_archivo in enumerate(archivos_a_procesar, start=1):
        nombre_archivo = os.path.basename(ruta_archivo)
        try:
            df = pd.read_csv(ruta_archivo)
            
            # Recorte matricial: Fila Excel 22 (índice 20) a 602 (índice 600)
            df_filtrado = df.iloc[20:601]
            
            # Promedio de las primeras 3 columnas (Componentes vectoriales X, Y, Z)
            promedios = df_filtrado.iloc[:, 0:3].mean()
            
            # Reemplazo de check de éxito por [OK]
            matriz_resumen.append({
                "Archivo": nombre_archivo,
                "Promedio_X": promedios.iloc[0],
                "Promedio_Y": promedios.iloc[1],
                "Promedio_Z": promedios.iloc[2]
            })
            print(f"   [{idx}/{len(archivos_a_procesar)}] OK - {nombre_archivo}")
        except Exception as e:
            print(f"   [{idx}/{len(archivos_a_procesar)}] Error en '{nombre_archivo}': {e}")

    if not matriz_resumen:
        print("Error: No se pudo extraer información válida de ningún archivo.")
        return None

    # Guardar reporte intermedio en disco (preservando máxima precisión)
    df_promedios = pd.DataFrame(matriz_resumen)
    ruta_salida_csv = os.path.join(carpeta_origen, archivo_csv_intermedio)
    df_promedios.to_csv(ruta_salida_csv, index=False, encoding="utf-8")
    print(f"\nReporte de promedios guardado con éxito en:\n   -> {ruta_salida_csv}\n")

    # ------------------------------------------------------------------------
    # PASO 2: Construcción de la Matriz Homogénea M (4x6)
    # ------------------------------------------------------------------------
    print("2. Construyendo la Matriz Homogénea M (Filas se vuelven Columnas)...")
    
    # Extraer los promedios numéricos como matriz pura de Numpy
    datos_numericos = df_promedios[['Promedio_X', 'Promedio_Y', 'Promedio_Z']].values
    
    # Transposición matricial (T): las filas de datos pasan a ser columnas
    matriz_transpuesta = datos_numericos.T
    
    # Crear la fila de la constante 1 para las 6 columnas (Coordenadas Homogéneas)
    num_columnas = matriz_transpuesta.shape[1]
    fila_unos = np.ones(num_columnas)
    
    # Acoplamiento vertical para dar la dimensión final de 4 x 6
    M = np.vstack([matriz_transpuesta, fila_unos])
    
    # ------------------------------------------------------------------------
    # PASO 3: Despliegue formal en consola
    # ------------------------------------------------------------------------
    print("\n======================================================================")
    print(f"MATRIZ HOMOGÉNEA 'M' GENERADA (Dimensión: {M.shape[0]}x{M.shape[1]})")
    print("======================================================================")
    
    # Configuración de formato estricto para NumPy (sin notación científica)
    np.set_printoptions(precision=8, suppress=True, linewidth=120)
    print(M)
    
    print("\nDesglose estructural de la memoria interna:")
    componentes = ["Fila 1 (Eje X)", "Fila 2 (Eje Y)", "Fila 3 (Eje Z)", "Fila 4 (Unos) "]
    for i, fila in enumerate(M):
        print(f"  {componentes[i]}: {fila}")
    print("======================================================================")
    
    return M

if __name__ == "__main__":
    # La variable M guardará la matriz lista para que la uses en cálculos futuros
    M = ejecutar_pipeline_completo()

    M_plus = np.linalg.pinv(M) # Pseudo-inversa de M

    print(M_plus)
    O_omega = np.dot(G, M_plus) # Producto matricial G * M^+

    print("\n======================================================================")
    print(f"MATRIZ RESULTANTE 'O_omega' (Dimensión: {O_omega.shape[0]}x{O_omega.shape[1]})")
    print("======================================================================")
    print(O_omega)