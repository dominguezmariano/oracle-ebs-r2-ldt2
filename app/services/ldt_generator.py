import io
import os
import re
import zipfile
from datetime import datetime

from .lct_parser import EntityDef, LctParser

LCT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'lct')


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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, lct_filename: str, root_params: dict,
                 connection, language: str = 'US') -> str:
        """Return LDT file content as a string."""
        lct_data = self._load_lct(lct_filename)
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

    def _load_lct(self, filename: str) -> dict:
        if filename not in self._lct_cache:
            path = os.path.join(self.lct_dir, filename)
            self._lct_cache[filename] = self._parser.parse_file(path)
        return self._lct_cache[filename]

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

    def _fetch_entity(self, entity: EntityDef, lct_data: dict,
                      bind_vars: dict, conn, indent: int) -> list:
        """Recursively fetch and format entity + children."""
        sql = lct_data['downloads'].get(entity.name)
        if not sql:
            return []

        rows = self._run_sql(conn, sql, bind_vars)
        lines = []
        prefix = '  ' * indent
        field_col_map = None

        for row in rows:
            # Build positional map once per query (FNDLOAD maps SQL columns by position,
            # not by name — column aliases in the SQL may differ from DEFINE field names).
            if field_col_map is None:
                sql_cols = list(row.keys())
                field_col_map = self._build_field_col_map(entity, sql_cols, lct_data)

            key_vals = [str(row.get(f.name) or '') for f in entity.key_fields]
            begin_keys = ' '.join(f'"{v}"' for v in key_vals)
            lines.append(f'{prefix}BEGIN {entity.name} {begin_keys}'.rstrip())

            for fdef in entity.non_key_fields:
                cols = field_col_map.get(fdef.name, [])
                if fdef.datatype == 'REFERENCES' and fdef.ref_entity:
                    vals = [str(row.get(c) or '') for c in cols]
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
                for fdef in entity.key_fields:
                    child_bind[fdef.name] = row.get(fdef.name)

                child_lines = self._fetch_entity(child, lct_data, child_bind, conn, indent + 1)
                if child_lines:
                    lines.append('')
                    lines.extend(child_lines)

            lines.append(f'{prefix}END {entity.name}')
            lines.append('')

        return lines

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
            cur.execute(working_sql, clean_params)
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
