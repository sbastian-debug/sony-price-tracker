import http.server
import socketserver
import urllib.parse
import json
import os
import re
import threading
from database import (
    init_db,
    get_products_summary,
    get_product_history,
    get_all_campaigns,
    get_campaign_detail,
    get_categories,
    get_collections,
    get_last_sync_status,
)
from scraper import run_full_sync

PORT = int(os.environ.get('PORT', 8080))
RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME', '').strip().lower()
RENDER_EXTERNAL_URL = os.environ.get('RENDER_EXTERNAL_URL', '').strip().rstrip('/')
IS_CLOUD_ENV = bool(os.environ.get('RENDER') or RENDER_EXTERNAL_HOSTNAME or RENDER_EXTERNAL_URL)
DEFAULT_HOST = '0.0.0.0' if IS_CLOUD_ENV else '127.0.0.1'
HOST = os.environ.get('SONY_TRACKER_HOST', DEFAULT_HOST)
BASE_DIR = os.path.dirname(os.path.realpath(__file__))
STATIC_DIR = os.path.realpath(os.path.join(BASE_DIR, 'static'))
BANNERS_DIR = os.path.realpath(os.path.join(BASE_DIR, 'data', 'banners'))

ALLOWED_ORIGINS = {
    f'http://localhost:{PORT}',
    f'http://127.0.0.1:{PORT}',
}
ALLOWED_HOSTS = {
    f'localhost:{PORT}',
    f'127.0.0.1:{PORT}',
    f'{HOST.lower()}:{PORT}',
}
if IS_CLOUD_ENV:
    ALLOWED_HOSTS.update({'localhost', '127.0.0.1'})

if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.add(RENDER_EXTERNAL_HOSTNAME)
    ALLOWED_HOSTS.add(f'{RENDER_EXTERNAL_HOSTNAME}:{PORT}')
    ALLOWED_ORIGINS.add(f'https://{RENDER_EXTERNAL_HOSTNAME}')
    ALLOWED_ORIGINS.add(f'http://{RENDER_EXTERNAL_HOSTNAME}')

if RENDER_EXTERNAL_URL:
    _parsed_render = urllib.parse.urlparse(RENDER_EXTERNAL_URL)
    if _parsed_render.netloc:
        ALLOWED_HOSTS.add(_parsed_render.netloc.lower())
        ALLOWED_ORIGINS.add(f'{_parsed_render.scheme}://{_parsed_render.netloc}')

for _extra_origin in os.environ.get('ALLOWED_ORIGINS', '').split(','):
    _clean_origin = _extra_origin.strip().rstrip('/')
    if _clean_origin:
        ALLOWED_ORIGINS.add(_clean_origin)
        _parsed_extra = urllib.parse.urlparse(_clean_origin)
        if _parsed_extra.netloc:
            ALLOWED_HOSTS.add(_parsed_extra.netloc.lower())

for _extra_host in os.environ.get('ALLOWED_HOSTS', '').split(','):
    _clean_host = _extra_host.strip().lower()
    if _clean_host:
        ALLOWED_HOSTS.add(_clean_host)

ALLOWED_STOCK_FILTERS = {'in_stock', 'out_of_stock', 'just_exhausted', 'restocked', 'all'}
ALLOWED_SORTS = {
    'discount_desc', 'price_changed', 'just_exhausted', 'restocked',
    'stock_asc', 'stock_desc', 'min_first', 'price_asc', 'price_desc', 'name_asc'
}
ALLOWED_STATIC_EXTS = {'.html', '.css', '.js', '.png', '.jpg', '.jpeg', '.webp', '.gif'}
ALLOWED_BANNER_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}

CONTENT_TYPES = {
    '.html': 'text/html; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.webp': 'image/webp',
    '.gif': 'image/gif',
}

CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' https://cdn.jsdelivr.net https://unpkg.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com; "
    "font-src 'self' https://fonts.gstatic.com https://unpkg.com data:; "
    "img-src 'self' data: https:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'"
)

is_syncing = False
sync_lock = threading.Lock()


class TrackerAPIHandler(http.server.BaseHTTPRequestHandler):
    def _is_valid_host(self):
        host = (self.headers.get('Host') or '').strip().lower()
        if not host:
            return False
        if host in ALLOWED_HOSTS:
            return True
        if IS_CLOUD_ENV:
            host_no_port = host.split(':')[0]
            if host_no_port.endswith('.onrender.com'):
                return True
            if self.command == 'GET' and (host_no_port.startswith('10.') or host_no_port.startswith('127.')):
                return True
        return False

    def _is_trusted_origin(self, origin):
        if not origin:
            return False
        norm = origin.strip().rstrip('/')
        if norm in ALLOWED_ORIGINS:
            return True
        if IS_CLOUD_ENV:
            try:
                parsed = urllib.parse.urlparse(norm)
                req_host = (self.headers.get('Host') or '').strip().lower()
                netloc = parsed.netloc.lower()
                if parsed.scheme == 'https' and (netloc == req_host or netloc.endswith('.onrender.com')):
                    return True
            except Exception:
                return False
        return False

    def end_headers(self):
        origin = self.headers.get('Origin')
        if origin and self._is_trusted_origin(origin):
            self.send_header('Access-Control-Allow-Origin', origin.strip().rstrip('/'))
            self.send_header('Vary', 'Origin')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Requested-With')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
        self.send_header('Permissions-Policy', 'geolocation=(), microphone=(), camera=(), usb=()')
        super().end_headers()

    def do_OPTIONS(self):
        origin = self.headers.get('Origin')
        if origin and not self._is_trusted_origin(origin):
            self.send_json_response({"error": "Origen no autorizado"}, status=403)
            return
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        try:
            if not self._is_valid_host():
                self.send_json_response({"error": "Host no autorizado"}, status=403)
                return

            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)

            # 1. API: Listado de productos
            if path == '/api/products':
                q = query.get('q', [''])[0].strip()[:120]
                cat = query.get('category', ['Todas'])[0].strip()[:80]
                collection = query.get('collection', ['Todas'])[0].strip()[:80]
                only_min = query.get('only_min', ['false'])[0].lower() == 'true'
                only_promo = query.get('only_promo', ['false'])[0].lower() == 'true'
                sort = query.get('sort', ['discount_desc'])[0].strip()
                stock = query.get('stock', ['all'])[0].strip()

                if stock not in ALLOWED_STOCK_FILTERS:
                    stock = 'all'
                if sort not in ALLOWED_SORTS:
                    sort = 'discount_desc'

                prods = get_products_summary(
                    search=q,
                    category=cat,
                    only_min=only_min,
                    stock_filter=stock,
                    sort_by=sort,
                    collection=collection,
                    only_promo=only_promo,
                )
                self.send_json_response(prods)
                return

            # 2. API: Historial de precio de un producto
            if path.startswith('/api/products/') and path.endswith('/history'):
                parts = path.strip('/').split('/')
                if len(parts) == 4:
                    prod_id = parts[2]
                    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', prod_id):
                        self.send_json_response({"error": "Identificador de producto inválido"}, status=400)
                        return
                    history_data = get_product_history(prod_id)
                    if history_data:
                        self.send_json_response(history_data)
                    else:
                        self.send_json_response({"error": "Producto no encontrado"}, status=404)
                    return

            # 3. API: Categorías disponibles
            if path == '/api/categories':
                cats = get_categories()
                self.send_json_response(cats)
                return

            # 3.1. API: Colecciones / Campañas internas disponibles
            if path == '/api/collections':
                cols = get_collections()
                self.send_json_response(cols)
                return

            # 4. API: Listado de campañas
            if path == '/api/campaigns':
                campaigns = get_all_campaigns()
                self.send_json_response(campaigns)
                return

            # 4.1. API: Estado de la última sincronización
            if path == '/api/sync/status':
                status = get_last_sync_status()
                with sync_lock:
                    status['is_syncing'] = is_syncing
                self.send_json_response(status)
                return

            # 5. API: Detalle de campaña y sus banners
            if path.startswith('/api/campaigns/'):
                parts = path.strip('/').split('/')
                if len(parts) == 3:
                    try:
                        camp_id = int(parts[2])
                        if camp_id <= 0:
                            raise ValueError()
                        camp_detail = get_campaign_detail(camp_id)
                        if camp_detail:
                            self.send_json_response(camp_detail)
                        else:
                            self.send_json_response({"error": "Campaña no encontrada"}, status=404)
                        return
                    except ValueError:
                        self.send_json_response({"error": "ID de campaña inválido"}, status=400)
                        return

            # 6. Servir archivos estáticos de frontend de forma segura
            if path == '/favicon.ico':
                self.send_response(204)
                self.end_headers()
                return

            if path == '/' or path == '/index.html':
                index_file = os.path.join(STATIC_DIR, 'index.html')
                self.serve_file_bytes(index_file, 'text/html; charset=utf-8', is_html=True)
                return

            if path.startswith('/static/'):
                rel_path = path[len('/static/'):]
                self.serve_safe_file(STATIC_DIR, rel_path, ALLOWED_STATIC_EXTS)
                return

            if path.startswith('/data/banners/'):
                rel_path = path[len('/data/banners/'):]
                self.serve_safe_file(BANNERS_DIR, rel_path, ALLOWED_BANNER_EXTS)
                return

            self.send_json_response({"error": "Recurso no encontrado"}, status=404)
        except Exception as e:
            print(f"Error interno en do_GET ({self.path}): {e}")
            self.send_json_response({"error": "Error interno del servidor"}, status=500)

    def _is_same_origin_post(self):
        """Valida origen y header anti-CSRF en peticiones mutantes (POST)."""
        req_with = self.headers.get('X-Requested-With', '')
        if req_with != 'SonyTrackerUI':
            return False

        origin = self.headers.get('Origin')
        if origin and not self._is_trusted_origin(origin):
            return False

        referer = self.headers.get('Referer')
        if referer:
            parsed_ref = urllib.parse.urlparse(referer)
            ref_origin = f"{parsed_ref.scheme}://{parsed_ref.netloc}"
            if not self._is_trusted_origin(ref_origin):
                return False

        return True

    def do_POST(self):
        try:
            if not self._is_valid_host():
                self.send_json_response({"error": "Host no autorizado"}, status=403)
                return

            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == '/api/sync':
                if not self._is_same_origin_post():
                    self.send_json_response({"error": "Solicitud bloqueada por política CSRF/Origen"}, status=403)
                    return

                global is_syncing
                with sync_lock:
                    if is_syncing:
                        self.send_json_response(
                            {"status": "ya_en_progreso", "mensaje": "Ya hay una sincronización activa"},
                            status=200
                        )
                        return
                    is_syncing = True

                def background_scrape():
                    global is_syncing
                    try:
                        print("Iniciando sincronización solicitada desde la Web...")
                        run_full_sync()
                        print("Sincronización finalizada exitosamente.")
                    except Exception as e:
                        print(f"Error en sincronización: {e}")
                    finally:
                        with sync_lock:
                            is_syncing = False

                threading.Thread(target=background_scrape, daemon=True).start()
                self.send_json_response({"status": "iniciado", "mensaje": "Sincronización en segundo plano iniciada"})
                return

            self.send_json_response({"error": "Ruta no encontrada"}, status=404)
        except Exception as e:
            print(f"Error interno en do_POST ({self.path}): {e}")
            self.send_json_response({"error": "Error interno del servidor"}, status=500)

    def send_json_response(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def serve_safe_file(self, base_dir, rel_path, allowed_exts):
        """Sirve un archivo estático garantizando confinamiento dentro de base_dir."""
        decoded = urllib.parse.unquote(rel_path)

        # Bloquear traversal, backslashes, bytes nulos, rutas absolutas o unidades Windows
        if (
            not decoded
            or '\x00' in decoded
            or '\\' in decoded
            or ':' in decoded
            or decoded.startswith('/')
            or '..' in decoded.split('/')
        ):
            self.send_json_response({"error": "Acceso denegado"}, status=403)
            return

        candidate = os.path.realpath(os.path.join(base_dir, *decoded.split('/')))
        try:
            in_bounds = os.path.commonpath([base_dir, candidate]) == base_dir
        except ValueError:
            in_bounds = False

        if not in_bounds or candidate == base_dir:
            self.send_json_response({"error": "Acceso denegado"}, status=403)
            return

        if not os.path.isfile(candidate):
            self.send_json_response({"error": "Archivo no encontrado"}, status=404)
            return

        ext = os.path.splitext(candidate)[1].lower()
        if ext not in allowed_exts:
            self.send_json_response({"error": "Tipo de archivo no permitido"}, status=403)
            return

        ct = CONTENT_TYPES.get(ext, 'application/octet-stream')
        self.serve_file_bytes(candidate, ct, is_html=(ext == '.html'))

    def serve_file_bytes(self, full_path, content_type, is_html=False):
        if not os.path.isfile(full_path):
            self.send_json_response({"error": "Archivo no encontrado"}, status=404)
            return
        with open(full_path, 'rb') as f:
            content = f.read()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(content)))
        if is_html:
            self.send_header('Content-Security-Policy', CSP_POLICY)
            self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(content)


def run_server(port=PORT, host=HOST):
    init_db()
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer((host, port), TrackerAPIHandler) as httpd:
        print("===========================================================")
        print(f" Servidor Sony Tracker activo en: http://{host}:{port}")
        print(f" Alias navegador local:           http://localhost:{port}")
        print(" Presiona Ctrl+C para detener el servidor")
        print("===========================================================")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServidor detenido.")


if __name__ == '__main__':
    run_server()
