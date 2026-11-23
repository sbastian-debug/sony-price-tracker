import http.server
import socketserver
import urllib.parse
import json
import os
import threading
from database import (
    init_db,
    get_products_summary,
    get_product_history,
    get_all_campaigns,
    get_campaign_detail,
    get_categories,
    get_last_sync_status,
    DB_PATH
)
from scraper import run_full_sync

PORT = int(os.environ.get('PORT', 8080))
BASE_DIR = os.path.dirname(__file__)
STATIC_DIR = os.path.join(BASE_DIR, 'static')
DATA_DIR = os.path.join(BASE_DIR, 'data')

is_syncing = False

class TrackerAPIHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # 1. API: Listado de productos
        if path == '/api/products':
            q = query.get('q', [''])[0].strip()
            cat = query.get('category', ['Todas'])[0].strip()
            only_min = query.get('only_min', ['false'])[0].lower() == 'true'
            sort = query.get('sort', ['discount_desc'])[0].strip()
            stock = query.get('stock', ['all'])[0].strip()

            prods = get_products_summary(search=q, category=cat, only_min=only_min, stock_filter=stock, sort_by=sort)
            self.send_json_response(prods)
            return

        # 2. API: Historial de precio de un producto
        elif path.startswith('/api/products/') and path.endswith('/history'):
            parts = path.strip('/').split('/')
            if len(parts) == 4:
                prod_id = parts[2]
                history_data = get_product_history(prod_id)
                if history_data:
                    self.send_json_response(history_data)
                else:
                    self.send_json_response({"error": "Producto no encontrado"}, status=404)
                return

        # 3. API: Categorías disponibles
        elif path == '/api/categories':
            cats = get_categories()
            self.send_json_response(cats)
            return

        # 4. API: Listado de campañas
        elif path == '/api/campaigns':
            campaigns = get_all_campaigns()
            self.send_json_response(campaigns)
            return

        # 4.1. API: Estado de la última sincronización
        elif path == '/api/sync/status':
            status = get_last_sync_status()
            status['is_syncing'] = is_syncing
            self.send_json_response(status)
            return

        # 5. API: Detalle de campaña y sus banners
        elif path.startswith('/api/campaigns/'):
            parts = path.strip('/').split('/')
            if len(parts) == 3:
                try:
                    camp_id = int(parts[2])
                    camp_detail = get_campaign_detail(camp_id)
                    if camp_detail:
                        self.send_json_response(camp_detail)
                    else:
                        self.send_json_response({"error": "Campaña no encontrada"}, status=404)
                    return
                except ValueError:
                    pass

        # 6. Servir archivos estáticos de frontend
        if path == '/' or path == '/index.html':
            self.serve_file(os.path.join(STATIC_DIR, 'index.html'), 'text/html; charset=utf-8')
            return
        elif path.startswith('/static/'):
            rel_path = path[len('/static/'):]
            file_path = os.path.join(STATIC_DIR, rel_path)
            self.serve_static_file(file_path)
            return
        elif path.startswith('/data/banners/'):
            rel_path = path[len('/data/banners/'):]
            file_path = os.path.join(DATA_DIR, 'banners', rel_path)
            self.serve_static_file(file_path)
            return

        self.send_error(404, "Recurso no encontrado")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/api/sync':
            global is_syncing
            if is_syncing:
                self.send_json_response({"status": "ya_en_progreso", "mensaje": "Ya hay una sincronización activa"}, status=200)
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
                    is_syncing = False

            threading.Thread(target=background_scrape, daemon=True).start()
            self.send_json_response({"status": "iniciado", "mensaje": "Sincronización en segundo plano iniciada"})
            return

        self.send_error(404, "Ruta no encontrada")

    def send_json_response(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_file(self, full_path, content_type):
        if os.path.exists(full_path):
            with open(full_path, 'rb') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_error(404, "Archivo no encontrado")

    def serve_static_file(self, full_path):
        if not os.path.exists(full_path):
            self.send_error(404, "Archivo estático no encontrado")
            return
        ext = os.path.splitext(full_path)[1].lower()
        content_types = {
            '.html': 'text/html; charset=utf-8',
            '.css': 'text/css; charset=utf-8',
            '.js': 'application/javascript; charset=utf-8',
            '.json': 'application/json; charset=utf-8',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.webp': 'image/webp',
            '.gif': 'image/gif',
            '.svg': 'image/svg+xml'
        }
        ct = content_types.get(ext, 'application/octet-stream')
        self.serve_file(full_path, ct)

def run_server(port=PORT):
    init_db()
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("", port), TrackerAPIHandler) as httpd:
        print(f"===========================================================")
        print(f" Servidor Sony Tracker activo en: http://localhost:{port}")
        print(f" Presiona Ctrl+C para detener el servidor")
        print(f"===========================================================")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServidor detenido.")

if __name__ == '__main__':
    run_server()
