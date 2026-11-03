import re
from dataclasses import dataclass, field as datafield


@dataclass
class FieldDef:
    field_type: str   # KEY, BASE, TRANS, CTX
    name: str
    datatype: str
    ref_entity: str = None  # set when datatype == 'REFERENCES'


@dataclass
class EntityDef:
    name: str
    fields: list = datafield(default_factory=list)
    children: list = datafield(default_factory=list)

    @property
    def key_fields(self):
        return [f for f in self.fields if f.field_type == 'KEY']

    @property
    def non_key_fields(self):
        return [f for f in self.fields if f.field_type != 'KEY']


class LctParser:
    """Parses Oracle FNDLOAD .lct configuration files."""

    def parse_file(self, path: str) -> dict:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        filename = re.split(r'[/\\]', path)[-1]
        return self.parse(content, filename=filename)

    def parse(self, content: str, filename: str = '') -> dict:
        entities, root_entities = self._parse_defines(content)
        downloads = self._parse_downloads(content)
        # Primary entity = last root entity in DOWNLOAD order (FNDLOAD downloads
        # dependencies before the main entity, so the main entity is always last).
        root_names_set = {e.name for e in root_entities}
        primary_entity = None
        for name in downloads:
            if name in root_names_set:
                primary_entity = name
        return {
            'ldrconfig': self._extract_ldrconfig(content, filename),
            'entities': entities,
            'root_entities': root_entities,
            'downloads': downloads,
            'define_block': self._extract_define_block_text(
                content, entities, primary_entity, downloads),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_ldrconfig(self, content: str, filename: str) -> str:
        m = re.search(r'\$Header:\s+(\S+\.lct\s+[\d.]+)', content)
        return m.group(1) if m else filename

    def _parse_defines(self, content: str):
        """Return (entities_dict, root_entities_list)."""
        entities = {}
        root_entities = []
        stack = []

        for line in content.split('\n'):
            s = line.strip()
            if not s or s.startswith('#') or s.startswith('COMMENT'):
                continue
            if re.match(r'^(DOWNLOAD|UPLOAD|PREPARE)\b', s):
                break

            m = re.match(r'^DEFINE\s+(\w+)', s)
            if m:
                ent = EntityDef(name=m.group(1))
                if stack:
                    stack[-1].children.append(ent)
                else:
                    root_entities.append(ent)
                entities[ent.name] = ent
                stack.append(ent)
                continue

            m = re.match(r'^END\s+\w+', s)
            if m and stack:
                stack.pop()
                continue

            m = re.match(r'^(KEY|BASE|TRANS|CTX)\s+(\w+)\s+(.*)', s)
            if m and stack:
                rest = m.group(3).strip()
                dtype = rest.split()[0] if rest else ''
                ref_m = re.match(r'REFERENCES\s+(\w+)', rest)
                ref_entity = ref_m.group(1) if ref_m else None
                stack[-1].fields.append(FieldDef(m.group(1), m.group(2), dtype, ref_entity))

        return entities, root_entities

    def _parse_downloads(self, content: str) -> dict:
        """Return dict {entity_name: sql_string}."""
        downloads = {}
        pattern = re.compile(r'DOWNLOAD\s+(\w+)\s*\n\s*"(.*?)"', re.DOTALL)
        for m in pattern.finditer(content):
            downloads[m.group(1)] = m.group(2).strip()
        return downloads

    def _reorder_block_children(self, lines: list, dl_order: list) -> list:
        """
        Reorder immediate nested DEFINE sub-blocks within a DEFINE block's lines
        so they appear in REVERSE DOWNLOAD order (later-downloaded child first).
        Applies recursively to each nested block's own children.
        """
        if not lines:
            return lines

        # lines[0] = "DEFINE NAME ...", lines[-1] = "END NAME"
        header = [lines[0]]
        footer = [lines[-1]] if len(lines) > 1 else []
        body = lines[1:len(lines) - 1] if len(lines) > 2 else []

        # Scan body for nested DEFINE blocks at depth 0 within this block
        field_lines = []    # field definitions before/between nested DEFINEs
        nested = []         # list of (name, [lines]) for each nested DEFINE
        depth = 0
        cur_name = None
        cur_block = []

        for line in body:
            s = line.strip()
            if depth == 0:
                m = re.match(r'^DEFINE\s+(\w+)', s)
                if m:
                    cur_name = m.group(1)
                    cur_block = [line]
                    depth = 1
                else:
                    field_lines.append(line)
            else:
                cur_block.append(line)
                if re.match(r'^DEFINE\b', s):
                    depth += 1
                elif re.match(r'^END\b', s):
                    depth -= 1
                    if depth == 0:
                        # Recurse into this nested block before storing
                        reordered = self._reorder_block_children(cur_block, dl_order)
                        nested.append((cur_name, reordered))
                        cur_name = None
                        cur_block = []

        if not nested:
            return lines

        # Sort nested blocks: later in DOWNLOAD → earlier in DEFINE output
        def _dl_pos(name):
            try:
                return dl_order.index(name)
            except ValueError:
                return len(dl_order)

        nested_sorted = sorted(nested, key=lambda x: _dl_pos(x[0]), reverse=True)

        # Reassemble: field lines first, then sorted nested blocks (blank line between)
        new_body = list(field_lines)
        for i, (_, blk) in enumerate(nested_sorted):
            if i > 0:
                new_body.append('')
            new_body.extend(blk)

        return header + new_body + footer

    def _extract_define_block_text(self, content: str,
                                    entities: dict = None,
                                    primary_entity: str = None,
                                    downloads: dict = None) -> str:
        """
        Extract top-level DEFINE blocks and reorder them to match FNDLOAD output:
        primary entity first, then referenced entities in DFS order (following
        REFERENCES fields recursively through children), then any remaining entities.
        Nested children within each block are reordered in reverse DOWNLOAD order.
        """
        # Collect lines up to the first DOWNLOAD/UPLOAD/PREPARE, skipping comments
        raw_lines = []
        depth = 0
        for line in content.split('\n'):
            s = line.strip()
            if s.startswith('#') or s.startswith('COMMENT'):
                continue
            if re.match(r'^(DOWNLOAD|UPLOAD|PREPARE)\b', s):
                break
            if re.match(r'^DEFINE\b', s):
                depth += 1
            if depth > 0:
                raw_lines.append(line.rstrip())
            if re.match(r'^END\b', s) and depth > 0:
                depth -= 1
        while raw_lines and not raw_lines[0].strip():
            raw_lines.pop(0)

        if not entities or not primary_entity:
            return '\n'.join(raw_lines)

        # Split raw_lines into top-level DEFINE blocks: name → [lines]
        top_blocks = {}   # preserves individual block lines
        lct_order = []    # LCT file order of top-level entities (fallback)
        cur_name = None
        cur_block = []
        blk_depth = 0
        for line in raw_lines:
            s = line.strip()
            m = re.match(r'^DEFINE\s+(\w+)', s)
            if m and blk_depth == 0:
                cur_name = m.group(1)
                blk_depth = 1
                cur_block = [line]
                lct_order.append(cur_name)
            elif blk_depth > 0:
                cur_block.append(line)
                if re.match(r'^DEFINE\b', s):
                    blk_depth += 1
                elif re.match(r'^END\b', s):
                    blk_depth -= 1
                    if blk_depth == 0:
                        top_blocks[cur_name] = cur_block
                        cur_name = None
                        cur_block = []

        # Reorder nested children within each top-level block (reverse DOWNLOAD order)
        dl_order = list(downloads.keys()) if downloads else []
        if dl_order:
            top_blocks = {
                name: self._reorder_block_children(blk, dl_order)
                for name, blk in top_blocks.items()
            }

        # DFS from primary_entity following REFERENCES fields.
        # Traverses the entity's own fields AND all children recursively.
        visited = []

        def _follow(ent):
            for fdef in ent.fields:
                if fdef.datatype == 'REFERENCES' and fdef.ref_entity:
                    ref = fdef.ref_entity
                    if ref not in visited and ref in top_blocks:
                        visited.append(ref)
                        if ref in entities:
                            _follow(entities[ref])
            for child in ent.children:
                _follow(child)

        if primary_entity in top_blocks:
            visited.append(primary_entity)
            if primary_entity in entities:
                _follow(entities[primary_entity])

        # Append any top-level entities not yet reached, in LCT file order
        for name in lct_order:
            if name not in visited and name in top_blocks:
                visited.append(name)

        # Reassemble
        parts = ['\n'.join(top_blocks[n]) for n in visited if n in top_blocks]
        return '\n\n'.join(parts)
