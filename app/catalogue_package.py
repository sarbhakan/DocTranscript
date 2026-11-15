"""Verify and extend the public, offline vocabulary without changing patient notes.

SQLite file headers/index layouts depend on the build host. Pin source bytes and
canonical relational content here; the app still pins the final SQLite *bytes*
in its compiled integrity header. No network or input from clinical notes.
"""
import hashlib
from contextlib import closing, contextmanager
import json
import os
import re
from pathlib import Path
import sqlite3
import tempfile

from lexique.__main__ import DDL

SOURCE_COLUMNS = 'id,title,edition,publication_date,url,license_url,attribution,sha256,format,note'


def domain_header(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    labels = data.get('labels', {})
    if data.get('schema') != 1 or not isinstance(labels, dict) or not labels:
        raise ValueError('Libellés de domaines absents ou non pris en charge.')
    lines = []
    for key, label in sorted(labels.items()):
        if (not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', key) or not isinstance(label, str)
                or not label.strip() or len(label) > 160 or any(ord(c) < 32 for c in label)):
            raise ValueError('Libellé de domaine invalide.')
        lines.append('    {' + json.dumps(key) + ', L' + json.dumps(label, ensure_ascii=False) + '},')
    return ('// Generated from reviewed domain_labels.json; UI labels only.\n'
            'constexpr std::pair<const char*, const wchar_t*> kCatalogueDomainLabels[] = {\n'
            + '\n'.join(lines) + '\n};\n')


@contextmanager
def open_readonly(path):
    con = sqlite3.connect(Path(path).resolve(strict=True).as_uri() + '?mode=ro&immutable=1', uri=True)
    try:
        con.execute('PRAGMA trusted_schema=OFF')
        yield con
    finally:
        con.close()


def content_digest(con):
    """Versioned, UTF-8 JSON-lines over every displayed/indexed relational value."""
    digest = hashlib.sha256(b'NoteVive-catalogue-content-v1\n')
    queries = (
        ('source', f'SELECT {SOURCE_COLUMNS} FROM source ORDER BY id'),
        ('term', 'SELECT source_id,code,label,search_label,category,label_kind FROM term '
                 'ORDER BY source_id,code,label'),
        ('specialty', 'SELECT t.source_id,t.code,t.label,s.name FROM specialty s '
                      'JOIN term t ON t.id=s.term_id ORDER BY t.source_id,t.code,t.label,s.name'),
    )
    for table, sql in queries:
        digest.update((table + '\n').encode())
        for row in con.execute(sql):
            digest.update((json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8'))
    return digest.hexdigest()


def check_schema(con):
    # Compare against a fresh schema, including FTS shadow tables and indexes.
    # Extra tables, columns, views, triggers and changed virtual-table options
    # cannot hitchhike on a valid digest of the known relational fields.
    sql = "SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name"
    with closing(sqlite3.connect(':memory:')) as expected:
        expected.executescript(DDL)
        if con.execute(sql).fetchall() != expected.execute(sql).fetchall():
            raise ValueError('Schéma du catalogue différent du format public autorisé.')


def validate(path, manifest, spec):
    cfg = json.loads(Path(manifest).read_text(encoding='utf-8'))
    expected_sources = cfg['sources']
    ids = [s['id'] for s in expected_sources]
    if len(set(ids)) != len(ids) or sorted(ids) != spec['sources']:
        raise ValueError('Sources du catalogue différentes du verrou public.')
    with open_readonly(path) as con:
        check_schema(con)
        expected = sorted(tuple(s[k] for k in SOURCE_COLUMNS.split(',')) for s in expected_sources)
        if (con.execute('PRAGMA user_version').fetchone() != (spec['schema'],)
                or con.execute('SELECT count(*) FROM term').fetchone() != (spec['entries'],)
                or con.execute(f'SELECT {SOURCE_COLUMNS} FROM source ORDER BY id').fetchall() != expected
                or con.execute('PRAGMA integrity_check').fetchone() != ('ok',)
                or con.execute('PRAGMA foreign_key_check').fetchone()
                or content_digest(con) != spec['content_sha256']):
            raise ValueError('Contenu du catalogue différent de l’instantané vérifié.')
        # FTS external-content integrity-check needs a writable connection. Check
        # a transient copy, not the immutable input; also catches corrupted indexes.
        with closing(sqlite3.connect(':memory:')) as copy:
            con.backup(copy)
            copy.execute("INSERT INTO term_fts(term_fts,rank) VALUES('integrity-check',1)")
    return cfg


def stage_catalogue(path, destination, manifest, spec):
    """Build the shipped file from approved columns, never copy opaque input bytes.

    Even a valid relational catalogue can carry unrelated data in free pages or
    appended bytes. Starting from DDL and selected rows removes that channel.
    """
    cfg = validate(path, manifest, spec)
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ValueError('Destination du catalogue déjà présente.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.catalogue-package-', dir=destination.parent) as tmp:
        stage = Path(tmp) / 'catalogue.sqlite'
        with open_readonly(path) as original, closing(sqlite3.connect(stage)) as clean:
            clean.executescript(DDL)
            with clean:
                clean.executemany('INSERT INTO source VALUES (?,?,?,?,?,?,?,?,?,?)',
                                  original.execute(f'SELECT {SOURCE_COLUMNS} FROM source ORDER BY id'))
                clean.executemany('INSERT INTO term VALUES (?,?,?,?,?,?,?)', original.execute(
                    'SELECT id,source_id,code,label,search_label,category,label_kind FROM term ORDER BY id'))
                clean.executemany('INSERT INTO specialty VALUES (?,?)', original.execute(
                    'SELECT term_id,name FROM specialty ORDER BY term_id,name'))
                clean.execute("INSERT INTO term_fts(term_fts) VALUES('rebuild')")
        validate(stage, manifest, spec)
        os.link(stage, destination)
    return cfg


def extend(base, additions, destination, domain_mapping=None):
    """Append a separately validated v2 catalogue; never overwrite either input."""
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ValueError('Choisir un nouveau fichier pour le catalogue enrichi.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.notevive-catalogue-', dir=destination.parent) as tmp:
        stage = Path(tmp) / 'catalogue.sqlite'
        with open_readonly(base) as original, open_readonly(additions) as extra, closing(sqlite3.connect(stage)) as con:
            if any(c.execute('PRAGMA user_version').fetchone() != (2,) for c in (original, extra)):
                raise ValueError('Schéma de vocabulaire non pris en charge.')
            original.backup(con)
            con.execute('PRAGMA foreign_keys=ON')
            with con:
                for row in extra.execute(f'SELECT {SOURCE_COLUMNS} FROM source ORDER BY id'):
                    con.execute('INSERT INTO source VALUES (?,?,?,?,?,?,?,?,?,?)', row)
                for row in extra.execute('SELECT id,source_id,code,label,search_label,category,label_kind '
                                         'FROM term ORDER BY source_id,code,label'):
                    new_id = con.execute('INSERT INTO term(source_id,code,label,search_label,category,label_kind) '
                                         'VALUES (?,?,?,?,?,?)', row[1:]).lastrowid
                    con.executemany('INSERT INTO specialty(term_id,name) VALUES (?,?)',
                                    [(new_id, name) for (name,) in extra.execute(
                                        'SELECT name FROM specialty WHERE term_id=? ORDER BY name', (row[0],))])
                seen = set()
                for row in (domain_mapping or {}).get('records', []):
                    if (set(row) != {'source_id', 'code', 'domain'} or row['source_id'] != 'orphanet-fr'
                            or not re.fullmatch(r'[0-9]+', row['code'])
                            or not re.fullmatch(r'orpha-[0-9]+', row['domain'])):
                        raise ValueError('Affectation officielle de domaine invalide.')
                    key = tuple(row[k] for k in ('source_id', 'code', 'domain'))
                    if key in seen:
                        raise ValueError('Affectation officielle de domaine dupliquée.')
                    seen.add(key)
                    ids = con.execute('SELECT id FROM term WHERE source_id=? AND code=?', key[:2]).fetchall()
                    if not ids:
                        raise ValueError('Affectation à un code absent du catalogue de base.')
                    con.executemany('INSERT OR IGNORE INTO specialty(term_id,name) VALUES (?,?)',
                                    [(term_id, row['domain']) for (term_id,) in ids])
                con.execute("INSERT INTO term_fts(term_fts) VALUES('rebuild')")
                con.execute("INSERT INTO term_fts(term_fts,rank) VALUES('integrity-check',1)")
            if con.execute('PRAGMA integrity_check').fetchone() != ('ok',) or con.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('Échec du contrôle du catalogue enrichi.')
        os.link(stage, destination)
