import sqlite3
import os
import json
import unicodedata
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'sony_tracker.db')

def _normalize_text(text):
    if text is None:
        return ''
    s = str(text)
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    return s.lower()

def _escape_like(text):
    return text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')

def get_connection(db_path=DB_PATH):
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.create_function('NORM_STR', 1, _normalize_text)
    return conn

def init_db(db_path=DB_PATH):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = get_connection(db_path)
    cur = conn.cursor()

    # Tabla de Productos
    cur.execute('''
    CREATE TABLE IF NOT EXISTS productos (
        id TEXT PRIMARY KEY,
        sku TEXT,
        nombre TEXT NOT NULL,
        categoria TEXT,
        url_producto TEXT,
        imagen_url TEXT,
        descripcion TEXT,
        colecciones_json TEXT DEFAULT '[]',
        highlights_json TEXT DEFAULT '[]',
        teasers_json TEXT DEFAULT '[]',
        regalos_json TEXT DEFAULT '[]',
        buy_together_json TEXT DEFAULT '[]',
        tiene_promo INTEGER DEFAULT 0,
        creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
        actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    for col_def in [
        "colecciones_json TEXT DEFAULT '[]'",
        "highlights_json TEXT DEFAULT '[]'",
        "teasers_json TEXT DEFAULT '[]'",
        "regalos_json TEXT DEFAULT '[]'",
        "buy_together_json TEXT DEFAULT '[]'",
        "tiene_promo INTEGER DEFAULT 0",
    ]:
        try:
            cur.execute(f"ALTER TABLE productos ADD COLUMN {col_def}")
        except Exception:
            pass

    # Tabla relacional de Colecciones / Campañas Internas por Producto
    cur.execute('''
    CREATE TABLE IF NOT EXISTS producto_colecciones (
        producto_id TEXT NOT NULL,
        cluster_id TEXT NOT NULL,
        nombre TEXT NOT NULL,
        PRIMARY KEY (producto_id, cluster_id),
        FOREIGN KEY (producto_id) REFERENCES productos (id) ON DELETE CASCADE
    )
    ''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_prod_col_nombre ON producto_colecciones(nombre)')

    # Tabla de Historial de Precios
    cur.execute('''
    CREATE TABLE IF NOT EXISTS historial_precios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        producto_id TEXT NOT NULL,
        precio REAL NOT NULL,
        precio_lista REAL,
        descuento_porcentaje REAL DEFAULT 0,
        disponible BOOLEAN DEFAULT 1,
        stock INTEGER DEFAULT 0,
        fecha_registro TEXT NOT NULL,
        FOREIGN KEY (producto_id) REFERENCES productos (id)
    )
    ''')

    # Índices para consultas rápidas
    cur.execute('CREATE INDEX IF NOT EXISTS idx_historial_prod ON historial_precios(producto_id)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_historial_fecha ON historial_precios(fecha_registro)')

    # Tabla de Campañas Publicitarias
    cur.execute('''
    CREATE TABLE IF NOT EXISTS campanas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        titulo TEXT NOT NULL,
        pre_header TEXT,
        descripcion TEXT,
        rango_fechas TEXT,
        fecha_primera_vez TEXT NOT NULL,
        fecha_ultima_vez TEXT NOT NULL,
        activa BOOLEAN DEFAULT 1,
        clave_unica TEXT UNIQUE
    )
    ''')

    # Tabla de Banners de la Campaña
    cur.execute('''
    CREATE TABLE IF NOT EXISTS banners_campana (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campana_id INTEGER NOT NULL,
        tipo TEXT DEFAULT 'desktop',
        url_remota TEXT NOT NULL,
        archivo_local TEXT,
        enlace_redireccion TEXT,
        texto_html TEXT,
        fecha_captura TEXT NOT NULL,
        FOREIGN KEY (campana_id) REFERENCES campanas (id)
    )
    ''')

    # Eliminar tablas de combos si existían
    cur.execute('DROP TABLE IF EXISTS combo_opciones')
    cur.execute('DROP TABLE IF EXISTS combos')

    # Tabla de Registro de Cambios de Precio
    cur.execute('''
    CREATE TABLE IF NOT EXISTS cambios_precio (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        producto_id TEXT NOT NULL,
        precio_anterior REAL NOT NULL,
        precio_nuevo REAL NOT NULL,
        diferencia REAL NOT NULL,
        porcentaje_cambio REAL NOT NULL,
        fecha_cambio TEXT NOT NULL,
        sync_id INTEGER,
        FOREIGN KEY (producto_id) REFERENCES productos (id)
    )
    ''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_cambios_prod ON cambios_precio(producto_id)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_cambios_fecha ON cambios_precio(fecha_cambio)')

    # Tabla de Registro de Productos que se Agotan (Quedan sin stock)
    cur.execute('''
    CREATE TABLE IF NOT EXISTS productos_agotados (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        producto_id TEXT NOT NULL,
        stock_anterior INTEGER NOT NULL,
        precio_momento REAL NOT NULL,
        fecha_agotado TEXT NOT NULL,
        sync_id INTEGER,
        FOREIGN KEY (producto_id) REFERENCES productos (id)
    )
    ''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_agotados_prod ON productos_agotados(producto_id)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_agotados_fecha ON productos_agotados(fecha_agotado)')

    # Tabla de Registro de Productos Reabastecidos (Volvieron a tener stock)
    cur.execute('''
    CREATE TABLE IF NOT EXISTS productos_reabastecidos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        producto_id TEXT NOT NULL,
        stock_anterior INTEGER NOT NULL,
        stock_nuevo INTEGER NOT NULL,
        precio_momento REAL NOT NULL,
        fecha_reabastecido TEXT NOT NULL,
        sync_id INTEGER,
        FOREIGN KEY (producto_id) REFERENCES productos (id)
    )
    ''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_reabastecidos_prod ON productos_reabastecidos(producto_id)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_reabastecidos_fecha ON productos_reabastecidos(fecha_reabastecido)')

    # Migración: Retroalimentar productos_reabastecidos desde historial si estaba vacía
    try:
        cur.execute('SELECT COUNT(*) FROM productos_reabastecidos')
        if cur.fetchone()[0] == 0:
            cur.execute('''
            INSERT INTO productos_reabastecidos (producto_id, stock_anterior, stock_nuevo, precio_momento, fecha_reabastecido)
            SELECT h1.producto_id, h1.stock, h2.stock, h2.precio, h2.fecha_registro
            FROM historial_precios h1
            JOIN historial_precios h2 ON h1.producto_id = h2.producto_id AND h2.id > h1.id
            WHERE (h1.stock = 0 OR h1.disponible = 0)
              AND (h2.stock > 0 AND h2.disponible = 1)
              AND NOT EXISTS (
                  SELECT 1 FROM historial_precios hm 
                  WHERE hm.producto_id = h1.producto_id AND hm.id > h1.id AND hm.id < h2.id
              )
            ''')
    except Exception as e:
        print(f"Nota en migración de reabastecidos: {e}")

    # Tabla de Historial de Sincronizaciones
    cur.execute('''
    CREATE TABLE IF NOT EXISTS sincronizaciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha_inicio TEXT NOT NULL,
        fecha_fin TEXT,
        estado TEXT DEFAULT 'en_progreso',
        total_productos INTEGER DEFAULT 0,
        cambios_detectados INTEGER DEFAULT 0,
        agotados_detectados INTEGER DEFAULT 0,
        reabastecidos_detectados INTEGER DEFAULT 0,
        detalles_json TEXT
    )
    ''')
    try:
        cur.execute('ALTER TABLE sincronizaciones ADD COLUMN agotados_detectados INTEGER DEFAULT 0')
    except Exception:
        pass
    try:
        cur.execute('ALTER TABLE sincronizaciones ADD COLUMN reabastecidos_detectados INTEGER DEFAULT 0')
    except Exception:
        pass

    # Habilitar modo WAL para concurrencia segura y recuperar sincronizaciones atascadas
    try:
        cur.execute('PRAGMA journal_mode = WAL')
    except Exception:
        pass
    cur.execute("UPDATE sincronizaciones SET estado = 'interrumpido' WHERE estado = 'en_progreso'")

    conn.commit()
    conn.close()

def start_sync(db_path=DB_PATH):
    conn = get_connection(db_path)
    cur = conn.cursor()
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute('''
    INSERT INTO sincronizaciones (fecha_inicio, estado, total_productos, cambios_detectados)
    VALUES (?, 'en_progreso', 0, 0)
    ''', (ahora,))
    sync_id = cur.lastrowid
    conn.commit()
    conn.close()
    return sync_id

def finish_sync(sync_id, total_productos, cambios_detectados, agotados_detectados=0, reabastecidos_detectados=0, detalles_json='', estado='completado', db_path=DB_PATH):
    conn = get_connection(db_path)
    cur = conn.cursor()
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute('''
    UPDATE sincronizaciones
    SET fecha_fin = ?, estado = ?, total_productos = ?, cambios_detectados = ?, agotados_detectados = ?, reabastecidos_detectados = ?, detalles_json = ?
    WHERE id = ?
    ''', (ahora, estado, total_productos, cambios_detectados, agotados_detectados, reabastecidos_detectados, detalles_json, sync_id))
    conn.commit()
    conn.close()

def get_last_sync_status(db_path=DB_PATH):
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute('SELECT * FROM sincronizaciones ORDER BY id DESC LIMIT 1')
    row = cur.fetchone()
    conn.close()
    if not row:
        return {"estado": "ninguna", "cambios_detectados": 0, "agotados_detectados": 0, "reabastecidos_detectados": 0}
    return dict(row)

def save_or_update_product(p, sync_id=None, db_path=DB_PATH):
    prod_id = str(p.get('id', '')).strip()
    if not prod_id:
        return None, None, None

    conn = get_connection(db_path)
    cur = conn.cursor()
    
    # 1. Obtener el último estado registrado en el historial para este producto
    cur.execute('''
    SELECT precio, disponible, stock
    FROM historial_precios
    WHERE producto_id = ?
    ORDER BY id DESC LIMIT 1
    ''', (prod_id,))
    last_rec = cur.fetchone()

    cambio_registrado = None
    agotado_registrado = None
    reabastecido_registrado = None
    fecha_hoy = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_price = float(p.get('precio', 0.0))
    new_stock = max(0, int(p.get('stock', 0)))
    new_disp = 1 if p.get('disponible', True) and new_stock > 0 and new_price > 0 else 0

    if last_rec:
        old_price = float(last_rec['precio'])
        old_stock = int(last_rec['stock'])
        old_disp = int(last_rec['disponible'])

        # 1. Verificar si cambió de precio
        if old_price > 0 and new_price > 0 and round(old_price, 2) != round(new_price, 2):
            diff = round(new_price - old_price, 2)
            pct = round((diff / old_price) * 100, 1)
            
            cur.execute('''
            INSERT INTO cambios_precio (producto_id, precio_anterior, precio_nuevo, diferencia, porcentaje_cambio, fecha_cambio, sync_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (prod_id, old_price, new_price, diff, pct, fecha_hoy, sync_id))
            
            cambio_registrado = {
                'producto_id': prod_id,
                'nombre': p.get('nombre', ''),
                'precio_anterior': old_price,
                'precio_nuevo': new_price,
                'diferencia': diff,
                'porcentaje': pct
            }

        # 2. Verificar si el producto se ACABA DE AGOTAR (tenía stock/disponible y ahora no)
        if (old_stock > 0 or old_disp == 1) and (new_stock == 0 or new_disp == 0):
            cur.execute('''
            INSERT INTO productos_agotados (producto_id, stock_anterior, precio_momento, fecha_agotado, sync_id)
            VALUES (?, ?, ?, ?, ?)
            ''', (prod_id, old_stock, old_price if old_price > 0 else new_price, fecha_hoy, sync_id))

            agotado_registrado = {
                'producto_id': prod_id,
                'nombre': p.get('nombre', ''),
                'stock_anterior': old_stock,
                'precio': old_price if old_price > 0 else new_price
            }

        # 3. Verificar si el producto VOLVIÓ A TENER STOCK (reabastecido)
        if (old_stock == 0 or old_disp == 0) and (new_stock > 0 and new_disp == 1):
            cur.execute('''
            INSERT INTO productos_reabastecidos (producto_id, stock_anterior, stock_nuevo, precio_momento, fecha_reabastecido, sync_id)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (prod_id, old_stock, new_stock, new_price, fecha_hoy, sync_id))

            reabastecido_registrado = {
                'producto_id': prod_id,
                'nombre': p.get('nombre', ''),
                'stock_anterior': old_stock,
                'stock_nuevo': new_stock,
                'precio': new_price
            }

    colecciones = p.get('colecciones') or []
    highlights = p.get('highlights') or []
    teasers = p.get('teasers') or []
    regalos = p.get('regalos') or []
    buy_together = p.get('buy_together') or []
    tiene_promo = 1 if (teasers or regalos or buy_together) else 0

    cur.execute('''
    INSERT INTO productos (
        id, sku, nombre, categoria, url_producto, imagen_url, descripcion,
        colecciones_json, highlights_json, teasers_json, regalos_json, buy_together_json, tiene_promo,
        actualizado_en
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(id) DO UPDATE SET
        sku=CASE WHEN excluded.sku != '' THEN excluded.sku ELSE productos.sku END,
        nombre=excluded.nombre,
        categoria=excluded.categoria,
        url_producto=excluded.url_producto,
        imagen_url=coalesce(excluded.imagen_url, productos.imagen_url),
        descripcion=excluded.descripcion,
        colecciones_json=excluded.colecciones_json,
        highlights_json=excluded.highlights_json,
        teasers_json=excluded.teasers_json,
        regalos_json=excluded.regalos_json,
        buy_together_json=excluded.buy_together_json,
        tiene_promo=excluded.tiene_promo,
        actualizado_en=CURRENT_TIMESTAMP
    ''', (
        prod_id,
        p.get('sku', ''),
        p['nombre'],
        p.get('categoria', 'General'),
        p.get('url_producto', ''),
        p.get('imagen_url', ''),
        p.get('descripcion', ''),
        json.dumps(colecciones, ensure_ascii=False),
        json.dumps(highlights, ensure_ascii=False),
        json.dumps(teasers, ensure_ascii=False),
        json.dumps(regalos, ensure_ascii=False),
        json.dumps(buy_together, ensure_ascii=False),
        tiene_promo
    ))

    # Actualizar colecciones normalizadas del producto
    cur.execute('DELETE FROM producto_colecciones WHERE producto_id = ?', (prod_id,))
    for col in colecciones:
        cid = str(col.get('id', '')).strip()
        cname = str(col.get('name', '')).strip()
        if cid and cname:
            cur.execute(
                'INSERT OR IGNORE INTO producto_colecciones (producto_id, cluster_id, nombre) VALUES (?, ?, ?)',
                (prod_id, cid, cname)
            )

    # Registrar en historial_precios usando new_disp coherente con stock y precio
    cur.execute('''
    INSERT INTO historial_precios (producto_id, precio, precio_lista, descuento_porcentaje, disponible, stock, fecha_registro)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        prod_id,
        new_price,
        p.get('precio_lista', new_price),
        p.get('descuento_porcentaje', 0) if new_disp == 1 else 0.0,
        new_disp,
        new_stock,
        fecha_hoy
    ))

    conn.commit()
    conn.close()
    return cambio_registrado, agotado_registrado, reabastecido_registrado

def _parse_json_field(raw_val):
    if not raw_val:
        return []
    try:
        parsed = json.loads(raw_val)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []

def get_products_summary(
    search=None,
    category=None,
    only_min=False,
    stock_filter='all',
    sort_by='discount_desc',
    collection=None,
    only_promo=False,
    db_path=DB_PATH
):
    conn = get_connection(db_path)
    cur = conn.cursor()

    query = '''
    WITH UltimaSync AS (
        SELECT COALESCE(MAX(id), 0) as last_sync_id
        FROM sincronizaciones
        WHERE estado = 'completado'
    ),
    UltimoPrecio AS (
        SELECT h1.*
        FROM historial_precios h1
        INNER JOIN (
            SELECT producto_id, MAX(id) as max_id
            FROM historial_precios
            GROUP BY producto_id
        ) h2 ON h1.id = h2.max_id
    ),
    MinimoHistorico AS (
        SELECT producto_id, MIN(precio) as min_historico, MAX(precio) as max_historico, COUNT(id) as registros_count
        FROM historial_precios
        WHERE disponible = 1 AND stock > 0 AND precio > 0
        GROUP BY producto_id
    ),
    UltimoCambio AS (
        SELECT c1.*
        FROM cambios_precio c1
        INNER JOIN (
            SELECT producto_id, MAX(id) as max_id
            FROM cambios_precio
            GROUP BY producto_id
        ) c2 ON c1.id = c2.max_id
    ),
    UltimoAgotado AS (
        SELECT a1.*
        FROM productos_agotados a1
        INNER JOIN (
            SELECT producto_id, MAX(id) as max_id
            FROM productos_agotados
            GROUP BY producto_id
        ) a2 ON a1.id = a2.max_id
    ),
    UltimoReabastecido AS (
        SELECT r1.*
        FROM productos_reabastecidos r1
        INNER JOIN (
            SELECT producto_id, MAX(id) as max_id
            FROM productos_reabastecidos
            GROUP BY producto_id
        ) r2 ON r1.id = r2.max_id
    )
    SELECT 
        p.id, p.sku, p.nombre, p.categoria, p.url_producto, p.imagen_url,
        p.colecciones_json, p.highlights_json, p.teasers_json, p.regalos_json, p.buy_together_json,
        COALESCE(p.tiene_promo, 0) as tiene_promo,
        COALESCE(u.precio, 0) as precio_actual,
        COALESCE(u.precio_lista, 0) as precio_lista,
        COALESCE(u.descuento_porcentaje, 0) as descuento_porcentaje,
        COALESCE(u.disponible, 0) as disponible,
        COALESCE(u.stock, 0) as stock,
        u.fecha_registro as ultima_actualizacion,
        COALESCE(m.min_historico, 0) as min_historico,
        COALESCE(m.max_historico, 0) as max_historico,
        COALESCE(m.registros_count, 0) as registros_count,
        CASE 
            WHEN u.disponible = 1 AND u.stock > 0 AND u.precio > 0 AND m.min_historico IS NOT NULL AND u.precio <= m.min_historico THEN 1 
            ELSE 0 
        END as es_minimo_historico,
        COALESCE(c.precio_anterior, 0) as precio_anterior,
        COALESCE(c.diferencia, 0) as diferencia_precio,
        COALESCE(c.porcentaje_cambio, 0) as porcentaje_cambio_precio,
        c.fecha_cambio as fecha_ultimo_cambio,
        CASE
            WHEN c.id IS NOT NULL AND c.sync_id = ls.last_sync_id AND c.diferencia != 0 THEN 1
            ELSE 0
        END as cambio_reciente,
        COALESCE(a.stock_anterior, 0) as agotado_stock_anterior,
        a.fecha_agotado,
        CASE 
            WHEN a.id IS NOT NULL AND (u.disponible = 0 OR u.stock = 0)
                 AND (r.fecha_reabastecido IS NULL OR a.fecha_agotado >= r.fecha_reabastecido) THEN 1 
            ELSE 0 
        END as recien_agotado,
        COALESCE(r.stock_anterior, 0) as reabastecido_stock_anterior,
        COALESCE(r.stock_nuevo, 0) as reabastecido_stock_nuevo,
        r.fecha_reabastecido,
        CASE 
            WHEN r.id IS NOT NULL AND u.disponible = 1 AND u.stock > 0
                 AND (a.fecha_agotado IS NULL OR r.fecha_reabastecido >= a.fecha_agotado) THEN 1 
            ELSE 0 
        END as recien_reabastecido
    FROM productos p
    CROSS JOIN UltimaSync ls
    LEFT JOIN UltimoPrecio u ON p.id = u.producto_id
    LEFT JOIN MinimoHistorico m ON p.id = m.producto_id
    LEFT JOIN UltimoCambio c ON p.id = c.producto_id
    LEFT JOIN UltimoAgotado a ON p.id = a.producto_id
    LEFT JOIN UltimoReabastecido r ON p.id = r.producto_id
    WHERE 1=1
    '''
    params = []

    if search:
        norm_search = _normalize_text(search)
        escaped = _escape_like(norm_search)
        term = f"%{escaped}%"
        query += " AND (NORM_STR(p.nombre) LIKE ? ESCAPE '\\' OR NORM_STR(p.categoria) LIKE ? ESCAPE '\\' OR NORM_STR(p.sku) LIKE ? ESCAPE '\\')"
        params.extend([term, term, term])

    if category and category != 'Todas':
        query += " AND p.categoria = ?"
        params.append(category)

    if collection and collection != 'Todas':
        query += " AND EXISTS (SELECT 1 FROM producto_colecciones pc WHERE pc.producto_id = p.id AND pc.nombre = ?)"
        params.append(collection)

    if only_promo:
        query += " AND COALESCE(p.tiene_promo, 0) = 1"

    # Evitar filtros contradictorios cuando sort_by pide modos especiales de disponibilidad
    if sort_by == 'just_exhausted' or stock_filter == 'just_exhausted':
        query += " AND a.id IS NOT NULL AND (u.disponible = 0 OR u.stock = 0) AND (r.fecha_reabastecido IS NULL OR a.fecha_agotado >= r.fecha_reabastecido)"
    elif sort_by == 'restocked' or stock_filter == 'restocked':
        query += " AND r.id IS NOT NULL AND u.disponible = 1 AND u.stock > 0 AND (a.fecha_agotado IS NULL OR r.fecha_reabastecido >= a.fecha_agotado)"
    elif stock_filter == 'in_stock':
        query += " AND u.disponible = 1 AND u.stock > 0 AND u.precio > 0"
    elif stock_filter == 'out_of_stock':
        query += " AND (u.disponible = 0 OR u.stock = 0 OR u.precio = 0)"

    if only_min and sort_by != 'just_exhausted' and stock_filter not in ('out_of_stock', 'just_exhausted'):
        query += " AND u.disponible = 1 AND u.stock > 0 AND u.precio > 0 AND m.min_historico IS NOT NULL AND u.precio <= m.min_historico"

    # Ordenamiento / Filtros Especiales
    if sort_by == 'price_changed':
        query += " AND c.id IS NOT NULL AND c.sync_id = ls.last_sync_id AND c.diferencia != 0"
        query += " ORDER BY c.id DESC, ABS(c.diferencia) DESC"
    elif sort_by == 'just_exhausted':
        query += " ORDER BY a.id DESC"
    elif sort_by == 'restocked':
        query += " ORDER BY r.id DESC, u.stock DESC"
    elif sort_by == 'stock_desc':
        query += " ORDER BY u.disponible DESC, u.stock DESC, p.nombre ASC"
    elif sort_by == 'stock_asc':
        # Prioriza los que tienen stock pero muy pocas unidades (a punto de agotarse)
        query += " ORDER BY u.disponible DESC, (CASE WHEN u.stock = 0 THEN 999999 ELSE u.stock END) ASC, p.nombre ASC"
    elif sort_by == 'discount_desc':
        # Primero los que tienen stock y mayor descuento
        query += " ORDER BY u.disponible DESC, (u.stock > 0) DESC, u.descuento_porcentaje DESC, p.nombre ASC"
    elif sort_by == 'price_asc':
        query += " ORDER BY u.disponible DESC, (u.stock > 0) DESC, (CASE WHEN u.precio = 0 THEN 999999 ELSE u.precio END) ASC"
    elif sort_by == 'price_desc':
        query += " ORDER BY u.disponible DESC, (u.stock > 0) DESC, u.precio DESC"
    elif sort_by == 'name_asc':
        query += " ORDER BY p.nombre ASC"
    elif sort_by == 'min_first':
        query += " ORDER BY es_minimo_historico DESC, u.disponible DESC, u.descuento_porcentaje DESC"
    else:
        query += " ORDER BY u.disponible DESC, u.descuento_porcentaje DESC"

    cur.execute(query, params)
    rows = cur.fetchall()
    results = []
    for r in rows:
        item = dict(r)
        item['colecciones'] = _parse_json_field(item.pop('colecciones_json', '[]'))
        item['highlights'] = _parse_json_field(item.pop('highlights_json', '[]'))
        item['teasers'] = _parse_json_field(item.pop('teasers_json', '[]'))
        item['regalos'] = _parse_json_field(item.pop('regalos_json', '[]'))
        item['buy_together'] = _parse_json_field(item.pop('buy_together_json', '[]'))
        results.append(item)
    conn.close()
    return results

def get_product_history(product_id, db_path=DB_PATH):
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute("SELECT * FROM productos WHERE id = ?", (product_id,))
    prod = cur.fetchone()
    if not prod:
        conn.close()
        return None

    product_dict = dict(prod)
    product_dict['colecciones'] = _parse_json_field(product_dict.pop('colecciones_json', '[]'))
    product_dict['highlights'] = _parse_json_field(product_dict.pop('highlights_json', '[]'))
    product_dict['teasers'] = _parse_json_field(product_dict.pop('teasers_json', '[]'))
    product_dict['regalos'] = _parse_json_field(product_dict.pop('regalos_json', '[]'))
    product_dict['buy_together'] = _parse_json_field(product_dict.pop('buy_together_json', '[]'))

    cur.execute('''
    SELECT precio, precio_lista, descuento_porcentaje, disponible, stock, fecha_registro
    FROM historial_precios
    WHERE producto_id = ?
    ORDER BY id ASC
    ''', (product_id,))
    history_rows = [dict(r) for r in cur.fetchall()]

    # Calcular estado coherente de reabastecido vs agotado
    latest = history_rows[-1] if history_rows else None
    cur_disp = latest['disponible'] if latest else 0
    cur_stock = latest['stock'] if latest else 0

    cur.execute('SELECT fecha_reabastecido FROM productos_reabastecidos WHERE producto_id = ? ORDER BY id DESC LIMIT 1', (product_id,))
    r_row = cur.fetchone()
    f_reab = r_row['fecha_reabastecido'] if r_row else None

    cur.execute('SELECT fecha_agotado FROM productos_agotados WHERE producto_id = ? ORDER BY id DESC LIMIT 1', (product_id,))
    a_row = cur.fetchone()
    f_agot = a_row['fecha_agotado'] if a_row else None

    product_dict['recien_reabastecido'] = 1 if (f_reab and cur_disp == 1 and cur_stock > 0 and (not f_agot or f_reab >= f_agot)) else 0
    product_dict['recien_agotado'] = 1 if (f_agot and (cur_disp == 0 or cur_stock == 0) and (not f_reab or f_agot >= f_reab)) else 0

    conn.close()
    return {
        "producto": product_dict,
        "historial": history_rows
    }

def sync_campaigns_active_state(active_keys, db_path=DB_PATH):
    """Marca como activas las campañas presentes en portada y como pasadas (0) las anteriores."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    if active_keys:
        placeholders = ','.join('?' for _ in active_keys)
        cur.execute(f"UPDATE campanas SET activa = 0 WHERE clave_unica NOT IN ({placeholders})", list(active_keys))
        cur.execute(f"UPDATE campanas SET activa = 1 WHERE clave_unica IN ({placeholders})", list(active_keys))
    else:
        cur.execute("UPDATE campanas SET activa = 0")
    conn.commit()
    conn.close()

def save_campaign_with_banners(camp_data, banners, db_path=DB_PATH):
    conn = get_connection(db_path)
    cur = conn.cursor()

    clave = camp_data.get('clave_unica')
    hoy = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("SELECT id FROM campanas WHERE clave_unica = ?", (clave,))
    row = cur.fetchone()

    if row:
        camp_id = row['id']
        cur.execute('''
        UPDATE campanas 
        SET fecha_ultima_vez = ?, activa = 1, titulo = ?, pre_header = ?, descripcion = ?, rango_fechas = ?
        WHERE id = ?
        ''', (
            hoy,
            camp_data['titulo'],
            camp_data.get('pre_header', ''),
            camp_data.get('descripcion', ''),
            camp_data.get('rango_fechas', ''),
            camp_id
        ))
    else:
        cur.execute('''
        INSERT INTO campanas (titulo, pre_header, descripcion, rango_fechas, fecha_primera_vez, fecha_ultima_vez, activa, clave_unica)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?)
        ''', (
            camp_data['titulo'],
            camp_data.get('pre_header', ''),
            camp_data.get('descripcion', ''),
            camp_data.get('rango_fechas', ''),
            hoy,
            hoy,
            clave
        ))
        camp_id = cur.lastrowid

    for b in banners:
        cur.execute('''
        SELECT id, archivo_local FROM banners_campana WHERE campana_id = ? AND url_remota = ?
        ''', (camp_id, b['url_remota']))
        b_row = cur.fetchone()
        if not b_row:
            cur.execute('''
            INSERT INTO banners_campana (campana_id, tipo, url_remota, archivo_local, enlace_redireccion, texto_html, fecha_captura)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                camp_id,
                b.get('tipo', 'desktop'),
                b['url_remota'],
                b.get('archivo_local', ''),
                b.get('enlace_redireccion', ''),
                b.get('texto_html', ''),
                hoy
            ))
        elif not b_row['archivo_local'] and b.get('archivo_local'):
            cur.execute('''
            UPDATE banners_campana SET archivo_local = ? WHERE id = ?
            ''', (b.get('archivo_local'), b_row['id']))

    conn.commit()
    conn.close()
    return camp_id

def get_all_campaigns(db_path=DB_PATH):
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute('''
    SELECT c.*, COUNT(b.id) as total_banners,
           (
               SELECT COALESCE(NULLIF(b2.archivo_local, ''), b2.url_remota)
               FROM banners_campana b2
               WHERE b2.campana_id = c.id
               ORDER BY CASE WHEN b2.tipo != 'mobile' THEN 0 ELSE 1 END, b2.id ASC
               LIMIT 1
           ) as banner_portada
    FROM campanas c
    LEFT JOIN banners_campana b ON c.id = b.campana_id
    GROUP BY c.id
    ORDER BY c.activa DESC, c.fecha_ultima_vez DESC
    ''')
    campaigns = [dict(r) for r in cur.fetchall()]
    conn.close()
    return campaigns

def get_campaign_detail(camp_id, db_path=DB_PATH):
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute("SELECT * FROM campanas WHERE id = ?", (camp_id,))
    camp = cur.fetchone()
    if not camp:
        conn.close()
        return None

    camp_dict = dict(camp)
    cur.execute("SELECT * FROM banners_campana WHERE campana_id = ? ORDER BY id ASC", (camp_id,))
    banners = [dict(r) for r in cur.fetchall()]
    camp_dict['banners'] = banners

    conn.close()
    return camp_dict

def get_categories(db_path=DB_PATH):
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute('''
    SELECT DISTINCT categoria 
    FROM productos 
    WHERE categoria IS NOT NULL AND categoria != ''
    ORDER BY categoria ASC
    ''')
    cats = [r['categoria'] for r in cur.fetchall()]
    conn.close()
    return cats

def get_collections(db_path=DB_PATH):
    """Lista las colecciones y campañas internas detectadas ordenadas por relevancia/cantidad."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute('''
    SELECT nombre, COUNT(DISTINCT producto_id) as total
    FROM producto_colecciones
    WHERE LOWER(nombre) NOT IN ('todos', 'despacho')
    GROUP BY nombre
    ORDER BY total DESC, nombre ASC
    ''')
    cols = [{'nombre': r['nombre'], 'total': r['total']} for r in cur.fetchall()]
    conn.close()
    return cols

def prune_inactive_collections(active_names, db_path=DB_PATH):
    """Elimina de la base de datos cualquier colección inactiva o interna fuera de active_names."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    norm_active = sorted({str(n).strip().lower() for n in (active_names or []) if str(n).strip()})
    if norm_active:
        placeholders = ','.join('?' for _ in norm_active)
        cur.execute(f"DELETE FROM producto_colecciones WHERE LOWER(nombre) NOT IN ({placeholders})", norm_active)
    else:
        cur.execute("DELETE FROM producto_colecciones")

    # Sincronizar colecciones_json también en productos que ya no aparecen en el catálogo vivo
    cur.execute("SELECT id, colecciones_json FROM productos WHERE colecciones_json IS NOT NULL AND colecciones_json != '[]'")
    for r in cur.fetchall():
        cols = _parse_json_field(r['colecciones_json'])
        filtered_cols = [
            c for c in cols
            if isinstance(c, dict) and str(c.get('name', '')).strip().lower() in norm_active
        ]
        if len(filtered_cols) != len(cols):
            cur.execute(
                "UPDATE productos SET colecciones_json = ? WHERE id = ?",
                (json.dumps(filtered_cols, ensure_ascii=False), r['id'])
            )
    conn.commit()
    conn.close()
