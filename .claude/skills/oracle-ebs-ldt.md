# Skill: oracle-ebs-ldt

Contexto de dominio y guía de trabajo para el proyecto **oracle-ebs-r2-ldt2**: un generador de archivos LDT/CNC para Oracle EBS R12.1.3 construido con Flask, dockerizado para Nebula, con temática R2-D2.

---

## Qué hace el proyecto

Lee archivos LCT locales (templates de control de FNDLOAD) + consulta Oracle EBS → genera archivos LDT/CNC listos para instalar vía FNDLOAD UPLOAD.

El flujo es:
1. El usuario selecciona objetos EBS desde la UI (búsqueda por tipo: LOOKUPS, CONCPROG, etc.)
2. La app lee el LCT correspondiente y ejecuta los SQL de DOWNLOAD contra Oracle
3. Genera el archivo en el formato FNDLOAD exacto, uno por idioma instalado (US, ESA, PTB…)
4. Entrega un ZIP con todos los archivos

---

## Estructura clave de archivos

| Archivo | Rol |
|---|---|
| `lct/` | LCT files locales (aflvmlu.lct, afcpprog.lct, …) |
| `app/services/lct_parser.py` | Parsea LCT → `EntityDef` / `FieldDef` |
| `app/services/ldt_generator.py` | Genera LDT consultando Oracle |
| `app/routes/download_manager.py` | Endpoint Flask; orquesta generación |
| `app/models/tipo_linea.py` | Config de tipos: extensión, lct_filename |
| `app/models/plantilla_ldt.py` | Templates de cmd FNDLOAD; `parametro_4` = template nombre archivo |
| `data/r2ldt2.db` | SQLite bind-mounted (persistencia en Docker) |

---

## Conceptos FNDLOAD/LCT que hay que conocer

### Estructura de un LCT

```
DEFINE ENTITY_NAME          ← schema (tipos de campo)
  KEY   FIELD_NAME   VARCHAR2(30)
  BASE  OTRO_CAMPO   REFERENCES OTRA_ENTIDAD
  ...
  DEFINE CHILD_ENTITY       ← entidad hija (anidada)
    KEY ...
  END CHILD_ENTITY
END ENTITY_NAME

DOWNLOAD ENTITY_NAME        ← SQL que consulta los datos
"SELECT col1, col2, ... FROM ... WHERE ..."
```

### Mapeo posicional de columnas SQL → DEFINE fields

**FNDLOAD mapea por POSICIÓN, no por alias de columna.** El generador replica esto en `_build_field_col_map`.

- Las KEY fields de la entidad ocupan las primeras N columnas del SELECT
- Los non-KEY fields se mapean en el orden en que aparecen en el DEFINE
- Un field `REFERENCES OTRA_ENTIDAD` consume tantas columnas como KEY fields tenga esa entidad

Ejemplo: `BASE EXEC REFERENCES EXECUTABLE` con EXECUTABLE teniendo KEY EXECUTABLE_NAME + KEY APPLICATION_SHORT_NAME → consume 2 columnas SQL consecutivas.

```python
# Alias con REFERENCES:
# BASE MLS_EXEC REFERENCES EXECUTABLE AS ME_EX_ID, ME_AP_ID
# → el AS es solo alias de columna en el SQL, el mapeo posicional
#   lo resuelve correctamente sin necesidad del alias
```

### Bind vars NULL en SQL de DOWNLOAD

Cuando una entidad "raíz" (como VALUE_SET en afcpprog.lct) tiene en su DOWNLOAD SQL una condición `AND col = :FLEX_VALUE_SET_NAME` pero ese bind var NO está en `root_params`, **NO se debe pasar NULL** (causaría `col = NULL` → 0 filas). En su lugar, se elimina esa condición del SQL y las otras condiciones de la subconsulta filtran correctamente.

Implementado en `_run_sql`: detecta bind vars None → stripea condiciones `AND col = :var` → consulta solo con los bind vars disponibles. Las condiciones `NVL(:var, '%')` se dejan intactas.

### FNDLOAD_BIG_FN

Valores de SQL que empiezan con `'FNDLOAD_BIG_FN:pkg.function(args)'` → FNDLOAD ejecuta `SELECT pkg.function(args) FROM DUAL`. Implementado en `_resolve_big_fn`.

### Orden de bloques en el archivo de salida

**El orden de DOWNLOAD en el LCT = orden de dependencia para UPLOAD = orden de los bloques BEGIN…END en el archivo generado.** Es crítico para el ERP.

Para afcpprog.lct: `EXECUTABLE → VALUE_SET → DESC_FLEX → PROGRAM`

El orden de los bloques DEFINE (schema) es cosmético — FNDLOAD UPLOAD lee todos los DEFINE antes de procesar datos.

### Formato multi-línea

```
FIELD_NAME =
 "primera linea\n\
  segunda linea\n\
  ultima linea"
```
El `\n\` es literal (backslash-n-backslash), no un escape Python.

---

## Añadir soporte para un nuevo tipo de objeto

1. **Copiar el LCT** al directorio `lct/` (obtenerlo del servidor EBS o de `$FND_TOP/patch/115/import/`)

2. **Agregar a `_TYPE_KEY_MAP`** en `download_manager.py`:
   ```python
   'NUEVO_TIPO': {
       'KEY_FIELD_ENTIDAD_RAIZ': 'OBJ_TYPE',   # campo KEY del LCT → campo del item
       'APPLICATION_SHORT_NAME': 'APP_SHORT_NAME',
       '_DERIVE': {                              # opcional: campos calculados
           'OTRO_PARAM': lambda p: p.get('KEY_FIELD_ENTIDAD_RAIZ'),
       },
   },
   ```

3. **Configurar TipoLinea** en la DB (UI: Configuración › Tipos de Línea):
   - `codigo`: ej. `NUEVO_TIPO`
   - `extension`: ej. `.ldt`
   - `lct_filename`: ej. `archivo.lct`

4. **Configurar PlantillaLdt** (UI: Configuración › Plantillas FNDLOAD):
   - `parametro_4`: template del nombre de archivo de salida, ej. `%OBJECT_NAME%_SUFIJO_%LANG%.ldt`
   - Comodines disponibles: `%OBJECT_NAME%`, `%APPL_SHORT_NAME%`, `%LANG%`, `$dbUser/$dbPass`

5. **Verificar** generando un archivo real y comparando contra uno producido por FNDLOAD en el servidor (en `ejemplos/fndloads/<tipo>/`).

### LCTs multi-objeto (`_TYPE_PRIMARY_ENTITY`)

Algunos LCT agrupan varios objetos (ej. `afscursp.lct`: usuarios, responsabilidades, aplicaciones, grupos de seguridad…). Con el modo clásico se volcarían TODAS las entidades raíz. Para estos tipos, registrar la entidad que realmente se descarga en `_TYPE_PRIMARY_ENTITY` (`download_manager.py`), p. ej. `'RESPONSIBILITIES': 'FND_RESPONSIBILITY'`. Entonces:

- Se emite solo la primaria y las entidades que referencia (`REFERENCES`), con sus claves exactas y en orden de dependencia (`FND_APPLICATION` antes de `FND_RESPONSIBILITY`).
- El bloque DEFINE incluye solo las entidades alcanzables y se normaliza al formato de FNDLOAD (sin tabs, sin `AS alias`, `KEY ... REFERENCES X` → tipo de la KEY de X).
- Sin filas para la primaria → `ValueError` (aparece en `_errores.txt` del ZIP).
- Las KEY se toman por nombre y, si el SQL usa otro alias (`RESP_KEY` vs `RESPONSIBILITY_KEY`), **por posición**.

Los tipos sin entrada en `_TYPE_PRIMARY_ENTITY` (LOOKUPS, CONCPROG) siguen con el modo clásico, sin cambios.

---

## Gotchas frecuentes

| Síntoma | Causa probable |
|---|---|
| Bloques BEGIN…END de una entidad completamente ausentes | Su DOWNLOAD SQL tiene `AND col = :BIND` con BIND no en root_params → NULL → 0 filas. Revisar `_run_sql` y la lógica de null vars. |
| Campos con valor vacío donde el servidor los tiene | El alias de columna SQL no coincide con el nombre del DEFINE field. Verificar con `_build_field_col_map` (mapeo posicional). |
| REFERENCES fields vacíos (EXEC, MLS_EXEC, SRS_FLEX) | Idem: el campo referenciado necesita N columnas positionales, no lookup por nombre. |
| `AUTO_ANNOTATION` vacío | Es un `FNDLOAD_BIG_FN` — revisar `_resolve_big_fn`. Requiere ejecutar la función en Oracle. |
| ORA-01036 illegal variable name/number | El SQL tiene un bind var que no existe en `bind_vars`. Revisar `_run_sql` y `params`. |
| Nombre de archivo incorrecto en el ZIP | `parametro_4` del PlantillaLdt no está configurado o no tiene extensión. Fallback: `{OBJ_TYPE}_{lang}.{ext}`. |

---

## Comandos FNDLOAD de referencia (notas.txt)

```bash
# LOOKUPS
FNDLOAD apps/pass 0 Y DOWNLOAD $FND_TOP/patch/115/import/aflvmlu.lct \
  "%OBJECT_NAME%_LKP_%LANG%.lkp" FND_LOOKUP_TYPE \
  APPLICATION_SHORT_NAME="%APPL_SHORT_NAME%" LOOKUP_TYPE="%OBJECT_NAME%"

# CONCPROG
FNDLOAD apps/pass 0 Y DOWNLOAD $FND_TOP/patch/115/import/afcpprog.lct \
  "%OBJECT_NAME%_CP_%LANG%.cnc" PROGRAM \
  APPLICATION_SHORT_NAME="%APPL_SHORT_NAME%" CONCURRENT_PROGRAM_NAME="%OBJECT_NAME%"
```

Mapeo de parámetros → `PlantillaLdt.parametro_N`:
- `parametro_1`: `$dbUser/$dbPass`
- `parametro_2`: `0 Y`
- `parametro_3`: ruta del LCT (`$FND_TOP/patch/115/import/archivo.lct`)
- `parametro_4`: **nombre del archivo de salida** (`%OBJECT_NAME%_CP_%LANG%.cnc`)
- `parametro_5`: entidad raíz (`PROGRAM`, `FND_LOOKUP_TYPE`, …)
- `parametro_6+`: pares `KEY=VALUE` con comodines
