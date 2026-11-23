import sqlite3
import os
import json
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'sony_tracker.db')

def get_connection(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
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
        creado_en DATETIME DEFAULT CURRENT_TIMESTAMP,
        actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')

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
        detalles_json TEXT
    )
    ''')
    try:
        cur.execute('ALTER TABLE sincronizaciones ADD COLUMN agotados_detectados INTEGER DEFAULT 0')
    except Exception:
        pass

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

def finish_sync(sync_id, total_productos, cambios_detectados, agotados_detectados=0, detalles_json='', estado='completado', db_path=DB_PATH):
    conn = get_connection(db_path)
    cur = conn.cursor()
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute('''
    UPDATE sincronizaciones
    SET fecha_fin = ?, estado = ?, total_productos = ?, cambios_detectados = ?, agotados_detectados = ?, detalles_json = ?
    WHERE id = ?
    ''', (ahora, estado, total_productos, cambios_detectados, agotados_detectados, detalles_json, sync_id))
    conn.commit()
    conn.close()

def get_last_sync_status(db_path=DB_PATH):
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute('SELECT * FROM sincronizaciones ORDER BY id DESC LIMIT 1')
    row = cur.fetchone()
    conn.close()
    if not row:
        return {"estado": "ninguna", "cambios_detectados": 0, "agotados_detectados": 0}
    return dict(row)

def save_or_update_product(p, sync_id=None, db_path=DB_PATH):
    conn = get_connection(db_path)
    cur = conn.cursor()
    
    # 1. Obtener el último estado registrado en el historial para este producto
    cur.execute('''
    SELECT precio, disponible, stock
    FROM historial_precios
    WHERE producto_id = ?
    ORDER BY id DESC LIMIT 1
    ''', (p['id'],))
    last_rec = cur.fetchone()

    cambio_registrado = None
    agotado_registrado = None
    fecha_hoy = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_price = float(p.get('precio', 0.0))
    new_stock = int(p.get('stock', 0))
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
            ''', (p['id'], old_price, new_price, diff, pct, fecha_hoy, sync_id))
            
            cambio_registrado = {
                'producto_id': p['id'],
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
            ''', (p['id'], old_stock, old_price if old_price > 0 else new_price, fecha_hoy, sync_id))

            agotado_registrado = {
                'producto_id': p['id'],
                'nombre': p.get('nombre', ''),
                'stock_anterior': old_stock,
                'precio': old_price if old_price > 0 else new_price
            }

    cur.execute('''
    INSERT INTO productos (id, sku, nombre, categoria, url_producto, imagen_url, descripcion, actualizado_en)
    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(id) DO UPDATE SET
        nombre=excluded.nombre,
        categoria=excluded.categoria,
        url_producto=excluded.url_producto,
        imagen_url=coalesce(excluded.imagen_url, productos.imagen_url),
        descripcion=excluded.descripcion,
        actualizado_en=CURRENT_TIMESTAMP
    ''', (
        p['id'],
        p.get('sku', ''),
        p['nombre'],
        p.get('categoria', 'General'),
        p.get('url_producto', ''),
        p.get('imagen_url', ''),
        p.get('descripcion', '')
    ))

    # Registrar en historial_precios
    cur.execute('''
    INSERT INTO historial_precios (producto_id, precio, precio_lista, descuento_porcentaje, disponible, stock, fecha_registro)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        p['id'],
        new_price,
        p.get('precio_lista', new_price),
        p.get('descuento_porcentaje', 0),
        1 if p.get('disponible', True) else 0,
        p.get('stock', 0),
        fecha_hoy
    ))

    conn.commit()
    conn.close()
    return cambio_registrado, agotado_registrado

def get_products_summary(search=None, category=None, only_min=False, stock_filter='all', sort_by='discount_desc', db_path=DB_PATH):
    conn = get_connection(db_path)
    cur = conn.cursor()

    query = '''
    WITH UltimoPrecio AS (
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
    )
    SELECT 
        p.id, p.sku, p.nombre, p.categoria, p.url_producto, p.imagen_url,
        COALESCE(u.precio, 0) as precio_actual,
        COALESCE(u.precio_lista, 0) as precio_lista,
        COALESCE(u.descuento_porcentaje, 0) as descuento_porcentaje,
        COALESCE(u.disponible, 0) as disponible,
        COALESCE(u.stock, 0) as stock,
        u.fecha_registro as ultima_actualizacion,
        COALESCE(m.min_historico, u.precio) as min_historico,
        COALESCE(m.max_historico, u.precio) as max_historico,
        COALESCE(m.registros_count, 1) as registros_count,
        CASE 
            WHEN u.disponible = 1 AND u.stock > 0 AND u.precio > 0 AND u.precio <= COALESCE(m.min_historico, u.precio) THEN 1 
            ELSE 0 
        END as es_minimo_historico,
        COALESCE(c.precio_anterior, 0) as precio_anterior,
        COALESCE(c.diferencia, 0) as diferencia_precio,
        COALESCE(c.porcentaje_cambio, 0) as porcentaje_cambio_precio,
        c.fecha_cambio as fecha_ultimo_cambio,
        COALESCE(a.stock_anterior, 0) as agotado_stock_anterior,
        a.fecha_agotado,
        CASE 
            WHEN a.id IS NOT NULL AND (u.disponible = 0 OR u.stock = 0) THEN 1 
            ELSE 0 
        END as recien_agotado
    FROM productos p
    LEFT JOIN UltimoPrecio u ON p.id = u.producto_id
    LEFT JOIN MinimoHistorico m ON p.id = m.producto_id
    LEFT JOIN UltimoCambio c ON p.id = c.producto_id
    LEFT JOIN UltimoAgotado a ON p.id = a.producto_id
    WHERE 1=1
    '''
    params = []

    if search:
        query += " AND (p.nombre LIKE ? OR p.categoria LIKE ? OR p.sku LIKE ?)"
        term = f"%{search}%"
        params.extend([term, term, term])

    if category and category != 'Todas':
        query += " AND p.categoria LIKE ?"
        params.append(f"%{category}%")

    # Filtro de stock: 'in_stock', 'out_of_stock', 'just_exhausted', 'all'
    if stock_filter == 'in_stock':
        query += " AND u.disponible = 1 AND u.stock > 0 AND u.precio > 0"
    elif stock_filter == 'out_of_stock':
        query += " AND (u.disponible = 0 OR u.stock = 0 OR u.precio = 0)"
    elif stock_filter == 'just_exhausted':
        query += " AND a.id IS NOT NULL AND (u.disponible = 0 OR u.stock = 0)"

    if only_min:
        query += " AND u.disponible = 1 AND u.stock > 0 AND u.precio > 0 AND (u.precio <= COALESCE(m.min_historico, u.precio))"

    # Ordenamiento / Filtros Especiales
    if sort_by == 'price_changed':
        query += " AND c.id IS NOT NULL AND c.diferencia != 0"
        query += " ORDER BY c.id DESC, ABS(c.diferencia) DESC"
    elif sort_by == 'just_exhausted':
        query += " AND a.id IS NOT NULL AND (u.disponible = 0 OR u.stock = 0)"
        query += " ORDER BY a.id DESC"
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
    results = [dict(r) for r in rows]
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

    cur.execute('''
    SELECT precio, precio_lista, descuento_porcentaje, disponible, stock, fecha_registro
    FROM historial_precios
    WHERE producto_id = ?
    ORDER BY fecha_registro ASC
    ''', (product_id,))
    history_rows = [dict(r) for r in cur.fetchall()]

    conn.close()
    return {
        "producto": product_dict,
        "historial": history_rows
    }

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
        SELECT id FROM banners_campana WHERE campana_id = ? AND url_remota = ?
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

    conn.commit()
    conn.close()
    return camp_id

def get_all_campaigns(db_path=DB_PATH):
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute('''
    SELECT c.*, COUNT(b.id) as total_banners, MIN(b.archivo_local) as banner_portada
    FROM campanas c
    LEFT JOIN banners_campana b ON c.id = b.campana_id
    GROUP BY c.id
    ORDER BY c.fecha_ultima_vez DESC
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
