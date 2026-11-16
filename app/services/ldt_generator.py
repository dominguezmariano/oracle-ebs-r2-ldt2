import io
import os
import re
import time
import logging
import zipfile
from datetime import datetime

from .lct_parser import EntityDef, LctParser

_log = logging.getLogger(__name__)
LCT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'lct')


class NoRowsError(ValueError):
    """La entidad primaria no devolvió filas."""

class LdtGenerator:
    """
    Generates LDT files by combining an LCT schema with live Oracle data.

    Usage:
        gen = LdtGenerator()
        ldt_text = gen.generate(
            lct_filename='aflvmlu.lct',
            root_params={'VIEW_APPSNAME': 'XBOL', 'LOOKUP_TYPE': 'XX_AR_FE_COUNTRIES'},
            connection=oracledb_conn,
            language='ESA',
        )
    """

    def __init__(self, lct_dir: str = None):
        self.lct_dir = lct_dir or LCT_DIR
        self._parser = LctParser()
        self._lct_cache = {}
        self._strict = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, lct_filename: str, root_params: dict,
                 connection, language: str = 'US',
                 primary_entity: str = None, deep_references: bool = False) -> str:
        """
        Return LDT file content as a string.

        primary_entity: para LCTs multi-objeto (ej. afscursp.lct). Si se indica, se emite
        solo esa entidad más las que referencia (en orden de dependencia), en vez de todas
        las entidades raíz del LCT.
        """
        # Formato "estricto" (escapado, continuación en columna 0, blancos con sangría)
        # solo para LCTs multi-objeto; el modo clásico queda exactamente como antes.
        self._strict = bool(primary_entity)
        lct_data = self._load_lct(lct_filename, primary_entity)
        self._set_nls(connection, language)
        source_db = self._get_db_name(connection)

        lines = [
            '# $Header$',
            '',
            f'LANGUAGE = "{language}"',
            f'LDRCONFIG = "{lct_data["ldrconfig"]}"',
            '',
            f'#Source Database {source_db}',
            '',
            '# -- Begin Entity Definitions -- ',
            '',
            lct_data['define_block'],
            '',
            '# -- End Entity Definitions -- ',
            '',
            '',
        ]

        if primary_entity:
            fetch = self._fetch_deep if deep_references else self._fetch_with_references
            try:
                lines.extend(fetch(primary_entity, lct_data, root_params, connection))
            except NoRowsError:
                # Sin traducción en este idioma: FNDLOAD genera igual el archivo, solo con
                # las definiciones (ver .msg PTB real). En US sí es un error (no existe).
                if language == "US":
                    raise
            lines.append('')    # los archivos reales terminan con una línea en blanco extra
            return '\n'.join(lines)

        # Generar datos en el orden de los bloques DOWNLOAD del LCT,
        # que es el orden correcto de dependencias para el instalador.
        root_names = {e.name for e in lct_data['root_entities']}
        for entity_name in lct_data['downloads']:
            if entity_name not in root_names:
                continue
            entity = lct_data['entities'][entity_name]
            data_lines = self._fetch_entity(
                entity, lct_data, root_params, connection, indent=0
            )
            lines.extend(data_lines)

        return '\n'.join(lines)

    def generate_all_languages(self, lct_filename: str, root_params: dict,
                               connection, object_name: str = 'ldt') -> bytes:
        """
        Generate one LDT file per installed language and return a ZIP as bytes.
        """
        languages = self._get_installed_languages(connection)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for lang_code in languages:
                try:
                    content = self.generate(lct_filename, root_params, connection, lang_code)
                    safe_name = re.sub(r'[^A-Za-z0-9_\-]', '_', object_name)
                    zf.writestr(f'{safe_name}_{lang_code}.ldt', content)
                except Exception as e:
                    zf.writestr(f'{object_name}_{lang_code}.ERROR.txt', str(e))
        buf.seek(0)
        return buf.read()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_lct(self, filename: str, primary_entity: str = None) -> dict:
        cache_key = (filename, primary_entity)
        if cache_key not in self._lct_cache:
            path = os.path.join(self.lct_dir, filename)
            self._lct_cache[cache_key] = self._parser.parse_file(
                path, primary_entity=primary_entity)
        return self._lct_cache[cache_key]

    def _get_db_name(self, conn) -> str:
        """Return the Oracle instance/DB name for the #Source Database header line."""
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT SYS_CONTEXT('USERENV', 'DB_NAME') FROM DUAL")
                row = cur.fetchone()
                if row and row[0]:
                    return str(row[0]).upper()
        except Exception:
            pass
        return 'UNKNOWN'

    def _set_nls(self, conn, language_code: str):
        """Set session NLS based on FND_LANGUAGES."""
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT NLS_LANGUAGE, NLS_TERRITORY FROM FND_LANGUAGES "
                    "WHERE LANGUAGE_CODE = :lc",
                    {'lc': language_code},
                )
                row = cur.fetchone()
                if row:
                    cur.execute(f"ALTER SESSION SET NLS_LANGUAGE = '{row[0]}'")
                    cur.execute(f"ALTER SESSION SET NLS_TERRITORY = '{row[1]}'")
        except Exception:
            pass  # fall back to session default

    def _get_installed_languages(self, conn) -> list:
        """Return list of language codes installed in this EBS instance."""
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT LANGUAGE_CODE FROM FND_LANGUAGES "
                    "WHERE INSTALLED_FLAG IN ('B', 'I') ORDER BY LANGUAGE_CODE"
                )
                return [r[0] for r in cur.fetchall()]
        except Exception:
            return ['US']

    @staticmethod
    def _key_values(entity: EntityDef, row: dict) -> list:
        """
        Valores de las KEY fields de una fila. Se busca por nombre y, si el SQL usa otro
        alias (ej. KEY RESP_KEY vs columna RESPONSIBILITY_KEY), se toma por POSICIÓN:
        FNDLOAD mapea por posición y las KEY son siempre las primeras columnas.
        """
        cols = list(row.keys())
        vals = []
        for i, f in enumerate(entity.key_fields):
            if f.name in row:
                vals.append(row[f.name])
            else:
                vals.append(row[cols[i]] if i < len(cols) else None)
        return vals

    def _fetch_entity(self, entity: EntityDef, lct_data: dict,
                      bind_vars: dict, conn, indent: int,
                      row_filter=None, ref_sink=None, rows_override=None) -> list:
        """Recursively fetch and format entity + children.

        ref_sink: si es una lista, se le agrega (entidad_referenciada, claves) por cada
        REFERENCES encontrado (en orden de aparición, incluyendo las entidades hijas).
        """
        sql = lct_data['downloads'].get(entity.name)
        if not sql:
            return []

        rows = rows_override if rows_override is not None else self._run_sql(conn, sql, bind_vars)
        if row_filter:
            rows = [r for r in rows if row_filter(r)]
        lines = []
        prefix = '  ' * indent
        field_col_map = None

        for row in rows:
            # Build positional map once per query (FNDLOAD maps SQL columns by position,
            # not by name — column aliases in the SQL may differ from DEFINE field names).
            if field_col_map is None:
                sql_cols = list(row.keys())
                field_col_map = self._build_field_col_map(entity, sql_cols, lct_data)

            key_vals = [str(v or '') for v in self._key_values(entity, row)]
            begin_keys = ' '.join(f'"{v}"' for v in key_vals)
            lines.append(f'{prefix}BEGIN {entity.name} {begin_keys}'.rstrip())

            for fdef in entity.non_key_fields:
                cols = field_col_map.get(fdef.name, [])
                if fdef.datatype == 'REFERENCES' and fdef.ref_entity:
                    vals = [str(row.get(c) or '') for c in cols]
                    if ref_sink is not None:
                        ref_sink.append((fdef.ref_entity, tuple(vals)))
                    if self._strict and not any(vals):
                        continue    # referencia sin ningún valor: FNDLOAD no la emite
                    val_str = ' '.join(f'"{v}"' for v in vals)
                    lines.append(f'{prefix}  {fdef.name} = {val_str}')
                elif cols:
                    val = row.get(cols[0])
                    if val is not None:
                        sval = str(val)
                        if sval.startswith('FNDLOAD_BIG_FN:'):
                            sval = self._resolve_big_fn(conn, sval)
                        if sval and sval.strip():
                            lines.extend(self._format_value_lines(
                                prefix + '  ', fdef.name, sval))

            for child in entity.children:
                child_bind = dict(bind_vars)
                for fdef, kval in zip(entity.key_fields, self._key_values(entity, row)):
                    child_bind[fdef.name] = kval

                child_lines = self._fetch_entity(child, lct_data, child_bind, conn, indent + 1,
                                                 ref_sink=ref_sink)
                if self._strict:
                    # FNDLOAD separa cada TIPO de hijo con un blanco con la sangría del
                    # padre, aunque ese tipo no tenga filas (ver ALR_ALERTS).
                    lines.append(prefix)
                    lines.extend(child_lines)
                elif child_lines:
                    lines.append('')
                    lines.extend(child_lines)

            lines.append(f'{prefix}END {entity.name}')
            # FNDLOAD deja la línea en blanco con la sangría del nivel (ver ejemplos reales)
            lines.append(prefix)

        return lines

    def _fetch_with_references(self, primary: str, lct_data: dict,
                               root_params: dict, conn) -> list:
        """
        Emite la entidad primaria precedida por las entidades que referencia
        (REFERENCES), en orden de dependencia, como hace FNDLOAD: solo las filas
        realmente referenciadas, no todas las del LCT.
        """
        entities = lct_data['entities']
        downloads = lct_data['downloads']
        entity = entities[primary]

        sql = downloads.get(primary)
        if not sql:
            raise ValueError(f"El LCT no tiene DOWNLOAD para {primary}")
        rows = self._run_sql(conn, sql, root_params)
        if not rows:
            raise NoRowsError(f"{primary}: sin resultados para {root_params}")

        # Claves referenciadas por entidad, sin duplicar y en orden de aparición
        refs: dict = {}

        def collect(ent: EntityDef, ent_rows: list):
            col_map = self._build_field_col_map(ent, list(ent_rows[0].keys()), lct_data)
            for row in ent_rows:
                for fdef in ent.non_key_fields:
                    if fdef.datatype != 'REFERENCES' or fdef.ref_entity not in entities:
                        continue
                    vals = tuple(str(row.get(c) or '') for c in col_map.get(fdef.name, []))
                    if not vals or not all(vals) or any(v == '*NULL*' for v in vals):
                        continue
                    seen = refs.setdefault(fdef.ref_entity, [])
                    if vals not in seen:
                        seen.append(vals)

        collect(entity, rows)

        order = list(downloads.keys())
        lines = []
        for ref_name in sorted(refs, key=lambda n: order.index(n) if n in order else len(order)):
            ref_ent = entities[ref_name]
            key_names = [f.name for f in ref_ent.key_fields]
            for key_tuple in refs[ref_name]:
                wanted = tuple(key_tuple)
                lines.extend(self._fetch_entity(
                    ref_ent, lct_data, dict(zip(key_names, key_tuple)), conn, 0,
                    row_filter=lambda r, e=ref_ent, w=wanted: tuple(
                        str(v or '') for v in self._key_values(e, r)) == w))

        lines.extend(self._fetch_entity(entity, lct_data, root_params, conn, 0))
        return lines

    def _fetch_deep(self, primary: str, lct_data: dict, root_params: dict, conn) -> list:
        """
        Cierre transitivo de referencias (menús: MENU -> ENTRY -> submenú/función -> form...).

        FNDLOAD emite cada objeto referenciado ANTES de quien lo referencia (recorrido en
        profundidad, post-orden), sin repetir, y en el orden en que aparecen los REFERENCES
        (campos del DEFINE; las entidades hijas en el orden de sus filas). Una referencia a
        '*NULL*' también se consulta (existe el menú '*NULL*'); si no devuelve filas no se emite.
        """
        entities = lct_data['entities']
        downloads = lct_data['downloads']
        primary_ent = entities[primary]
        seen: set = set()
        out: list = []

        def emit(ent: EntityDef, params: dict, row_filter, key, rows_override=None):
            sink: list = []
            lines = self._fetch_entity(ent, lct_data, params, conn, 0,
                                       row_filter=row_filter, ref_sink=sink,
                                       rows_override=rows_override)
            if not lines:
                return False
            for ref_name, vals in sink:
                if ref_name in entities and ref_name in downloads and any(vals):
                    visit(ref_name, vals)
            out.extend(lines)
            return True

        # Carga masiva: una entidad sin hijas (FUNCTION, FORM, OBJECT) que se consulta muchas
        # veces se trae completa en UNA consulta (todas sus binds nulas) y se indexa por clave.
        # Un menú grande hace >1.400 consultas de funciones; una por una supera el timeout.
        BULK_AFTER = 8
        counts: dict = {}
        bulk: dict = {}     # entidad -> {claves: [filas]} | None (si la carga masiva falló)

        def bulk_rows(ref_name: str, ref_ent: EntityDef, vals: tuple):
            counts[ref_name] = counts.get(ref_name, 0) + 1
            if ref_name not in bulk and counts[ref_name] > BULK_AFTER:
                try:
                    index: dict = {}
                    for r in self._run_sql(conn, downloads[ref_name], {}):
                        k = tuple(str(v or '') for v in self._key_values(ref_ent, r))
                        index.setdefault(k, []).append(r)
                    bulk[ref_name] = index
                except Exception:
                    bulk[ref_name] = None
            index = bulk.get(ref_name)
            return None if index is None else index.get(vals, [])

        def visit(ref_name: str, vals: tuple):
            key = (ref_name, vals)
            if key in seen:
                return
            seen.add(key)
            ref_ent = entities[ref_name]
            names = [f.name for f in ref_ent.key_fields]
            emit(ref_ent, dict(zip(names, vals)),
                 lambda r, e=ref_ent, w=vals: tuple(
                     str(v or '') for v in self._key_values(e, r)) == w, key,
                 rows_override=bulk_rows(ref_name, ref_ent, vals))

        # Entidad primaria: puede devolver varias filas (patrón LIKE); se marcan como vistas
        rows = self._run_sql(conn, downloads[primary], root_params)
        if not rows:
            raise NoRowsError(f"{primary}: sin resultados para {root_params}")
        for r in rows:
            seen.add((primary, tuple(str(v or '') for v in self._key_values(primary_ent, r))))
        emit(primary_ent, root_params, None, None, rows_override=rows)
        return out

    def _build_field_col_map(self, entity: EntityDef, sql_cols: list, lct_data: dict) -> dict:
        """
        Map each non-KEY DEFINE field to its SQL column(s) by position.
        REFERENCES fields consume N columns (one per key of the referenced entity).
        """
        col_idx = len(entity.key_fields)
        result = {}
        for fdef in entity.non_key_fields:
            if fdef.datatype == 'REFERENCES' and fdef.ref_entity:
                ref_ent = lct_data['entities'].get(fdef.ref_entity)
                n = len(ref_ent.key_fields) if ref_ent else 1
                result[fdef.name] = sql_cols[col_idx:col_idx + n]
                col_idx += n
            else:
                if col_idx < len(sql_cols):
                    result[fdef.name] = [sql_cols[col_idx]]
                col_idx += 1
        return result

    def _resolve_big_fn(self, conn, fn_marker: str) -> str:
        """Execute a FNDLOAD_BIG_FN deferred function call and return the result."""
        fn_call = fn_marker[len('FNDLOAD_BIG_FN:'):]
        try:
            with conn.cursor() as cur:
                cur.execute(f'SELECT {fn_call} FROM DUAL')
                row = cur.fetchone()
                if row and row[0]:
                    return str(row[0])
        except Exception:
            pass
        return ''

    def _format_value_lines(self, field_prefix: str, name: str, val: str) -> list:
        """
        Format a field=value pair, using FNDLOAD multi-line continuation when
        the value contains newlines or is very long.
        """
        if self._strict:
            return self._format_value_lines_strict(field_prefix, name, val)
        if '\n' not in val:
            return [f'{field_prefix}{name} = "{val}"']
        # Multi-line: FNDLOAD uses  "line1\n\<newline>  line2\n\<newline>  last"
        parts = val.split('\n')
        cont = '\\n\\'   # literal characters: backslash n backslash
        out = [f'{field_prefix}{name} =']
        for i, part in enumerate(parts):
            is_last = (i == len(parts) - 1)
            suffix = '' if is_last else cont
            if i == 0:
                out.append(f' "{part}{suffix}')
            else:
                out.append(f'  {part}{suffix}')
        # Close the last line with "
        out[-1] += '"'
        return out

    @staticmethod
    def _format_value_lines_strict(field_prefix: str, name: str, val: str) -> list:
        """
        Formato de valor tal como lo escribe FNDLOAD (verificado contra un .alr real):
          - se escapan  \\  ->  \\\\   y   "  ->  \\"
          - un valor multilínea abre con  NAME =  y luego ` "primera\\n\\`
          - las líneas de continuación van en columna 0 (el texto tal cual)
          - si el valor termina en salto de línea, el cierre es  `" ` (comilla + espacio)
        """
        esc = lambda t: t.replace('\\', '\\\\').replace('"', '\\"')
        # FNDLOAD también parte los valores largos aunque no tengan saltos de línea:
        # si la línea `<sangría>NAME = "valor"` (valor sin escapar) llega a 80 caracteres
        # pasa a la forma multilínea. Medido sobre ~130k líneas de archivos reales:
        # 0 excepciones (la línea simple más larga mide 79, la multilínea más corta 80).
        if '\n' not in val and len(field_prefix) + len(name) + len(val) + 5 < 80:
            return [f'{field_prefix}{name} = "{esc(val)}"']
        parts = [esc(p) for p in val.split('\n')]
        out = [f'{field_prefix}{name} =']
        for i, part in enumerate(parts):
            last = i == len(parts) - 1
            if last:
                line = part + '"' + (' ' if part == '' else '')
            else:
                line = part + '\\n\\'
            out.append(f' "{line}' if i == 0 else line)
        return out

    def _run_sql(self, conn, sql: str, bind_vars: dict) -> list:
        """Execute DOWNLOAD SQL and return rows as list of dicts."""
        # Strip single-quoted string literals before searching for bind vars
        # to avoid false positives like 'FNDLOAD_BIG_FN:FND_SOME_PKG...'
        sql_no_literals = re.sub(r"'[^']*'", "''", sql)
        bind_names = list(dict.fromkeys(re.findall(r':(\w+)', sql_no_literals)))
        params = {n: bind_vars.get(n) for n in bind_names}

        # For None-valued bind vars, handle them case by case:
        #   - If the SQL has  "AND col = :VAR"  (strict equality), passing NULL would make
        #     the condition always false and return 0 rows.  Strip the whole condition and
        #     remove the var from params so Oracle doesn't see it at all.  This lets root
        #     entities like VALUE_SET (whose KEY isn't in root_params) still return rows
        #     filtered by the other available params.
        #   - Any other pattern — (:VAR is null), NVL(:VAR, …), LIKE — already handles
        #     NULL correctly in Oracle.  Keep those vars in params, passing them as NULL.
        working_sql = sql
        stripped_vars = set()
        for var, val in params.items():
            if val is None:
                new_sql = re.sub(
                    r'(?i)\s+AND\s+\w+(?:\.\w+)?\s*=\s*:' + re.escape(var) + r'\b',
                    '', working_sql
                )
                if new_sql != working_sql:
                    working_sql = new_sql
                    stripped_vars.add(var)
        clean_params = {n: v for n, v in params.items() if n not in stripped_vars}

        with conn.cursor() as cur:
            _t0 = time.monotonic()
            cur.execute(working_sql, clean_params)
            _dt = time.monotonic() - _t0
            if _dt > 1.0:
                _log.warning('consulta lenta (%.1fs): %s | %s', _dt,
                             ' '.join(working_sql.split())[:90], clean_params)
            # De-duplicate column names: Oracle can return the same column name
            # multiple times (e.g. VALUE_SET selects fvs.flex_value_set_name at col[0]
            # AND fvs_parent.flex_value_set_name at col[15], both named FLEX_VALUE_SET_NAME).
            # dict(zip(dupes, row)) would silently overwrite col[0] with col[15],
            # corrupting the KEY value and shifting all positional mappings.
            seen: dict = {}
            cols = []
            for d in cur.description:
                name = d[0]
                if name in seen:
                    seen[name] += 1
                    cols.append(f'{name}_{seen[name]}')
                else:
                    seen[name] = 1
                    cols.append(name)
            return [dict(zip(cols, r)) for r in cur.fetchall()]
