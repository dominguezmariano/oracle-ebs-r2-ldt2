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

Tipos registrados hoy: `RESPONSIBILITIES` (`FND_RESPONSIBILITY`, afscursp.lct), `ALERTS` (`ALR_ALERTS`, alr.lct, con 13 entidades hijas anidadas) y `VALUESETS` (`VALUE_SET`, afffload.lct, que también contiene DESC_FLEX/KEY_FLEX/etc. que NO se descargan).

También `MENU` (`MENU`, afsload.lct, ext `.men`), con **cierre transitivo de referencias** (`_TYPE_DEEP_REFERENCES` → `LdtGenerator._fetch_deep`): MENU → ENTRY → submenú/función → form/object. Cada objeto sale ANTES de quien lo referencia (post-orden en profundidad), sin repetir, en el orden de aparición de los REFERENCES (campos del DEFINE; hijos por fila). Una referencia a `*NULL*` también se consulta (existe el menú `*NULL*`, sale primero); si no devuelve filas no se emite. Un menú real grande hace ~2.000 consultas por idioma (de ahí el `--timeout 900` de gunicorn).

`FNDMSGS` (`FND_NEW_MESSAGES`, afmdmsg.lct, `.msg`): entidad única sin referencias; claves `APPLICATION_SHORT_NAME` / `MESSAGE_NAME`. Su SQL filtra `language_code = userenv('LANG')`, por eso depende del `ALTER SESSION NLS_LANGUAGE` de `_set_nls`.

Codificación del ZIP: US en ASCII y ESA/PTB en latin-1 (como el NLS_LANG de las plantillas FNDLOAD); lo que no cabe sale como `?`.

Los hijos se recorren en el orden del DEFINE, que en estos tres LCT coincide con el orden de los bloques DOWNLOAD (así lo hace FNDLOAD). Si un LCT nuevo los tuviera distintos, hay que ordenar por DOWNLOAD.

Cómo verificar un tipo nuevo sin Oracle: servir como "Oracle" los datos de un archivo real (parsear sus bloques BEGIN…END y devolverlos como filas de cada SQL, filtrando por las claves del padre) y comparar la salida. Ojo: solo valida lo que el ejemplo contiene; revisar aparte que cada SQL hijo reciba sus binds (un `AND col = :VAR` con NULL se descarta en `_run_sql`).

**Formato "estricto"** (solo en este modo; verificado contra `.rsp`, `.alr` y `.vls` reales de FNDLOAD):

- DEFINE: los hijos van en orden inverso al DOWNLOAD y cada DEFINE hijo se indenta `padre + 2 + 2 × (hermanos ya impresos)` — de ahí la "escalera" de ALR_ALERTS. Sin blancos repetidos.
- Valores: se escapa `\` → `\\` y `"` → `\"`. Multilínea: abre `NAME =` / ` "primera\n\`, las continuaciones van en **columna 0**, y si el valor termina en salto de línea el cierre es `" ` (comilla + espacio).
- Entre tipos de hijo hay una línea en blanco con la **sangría del padre**, también para tipos sin filas; cada fila cierra con una línea en blanco con su propia sangría; el archivo termina con un blanco extra.
- Los valores largos también se parten aunque no tengan saltos: si `<sangría>NAME = "valor"` (valor sin escapar) mide ≥ 80 caracteres, sale como `NAME =` / ` "valor"`. Medido sobre ~130k líneas reales sin excepciones (la simple más larga mide 79).
- Una referencia sin ningún valor no se emite (FNDLOAD siempre trae `*NULL*`; solo ocurre con datos simulados).
- En el bloque DEFINE, los REFERENCES de una entidad se recorren en orden inverso para ordenar las entidades alcanzables (FUNCTION: OBJECT antes que FORM).
- El nombre del archivo conserva los espacios (`XX AR FE Argentina_ALRT_US.alr`).

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
