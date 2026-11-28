# SonyBoliviaDB — Monitor de Precios, Stock, Colecciones & Archivo de Campañas

Aplicación web con diseño **Liquid Glass UI (iOS)** para rastrear el catálogo completo de **Sony Store Bolivia** (`store.sony.com.bo`), monitorear variaciones exactas de precios y unidades en stock con gráficas históricas escalonadas, detectar **mínimos históricos (All-Time Low)**, alertar sobre productos **recién agotados** o **reabastecidos**, identificar **promociones, regalos, Buy Together y colecciones activas**, y archivar **campañas publicitarias** (slider principal, cintillos, Imperdibles, Favoritos Sony, popups/cupones y Secret Sale).

## Estructura del Proyecto

- `database.py`: Gestión de base de datos SQLite (`WAL` y claves foráneas activas) con tablas para productos, histórico de precios y stock, colecciones activas normalizadas, cambios de precio, agotados, reabastecidos, campañas, banners y registro de sincronizaciones.
- `scraper.py`: Extractor automático que consulta los lotes de catálogo de Sony Store Bolivia, extrae variantes/SKUs, promociones (`PromotionTeasers`, `GiftSkuIds`, `BuyTogether`) y colecciones vigentes (`blackfriday`, `campana-camaras`, `nuevo`), descarga y valida de forma segura imágenes de campañas/banners y actualiza el estado activo/pasado de campañas.
- `server.py`: Servidor HTTP local seguro (`127.0.0.1:8080`) con cabeceras de seguridad (CSP sin `unsafe-inline` en scripts, `X-Frame-Options`, `X-Content-Type-Options`), protección CSRF/Host, prevención de Path Traversal y API REST en JSON.
- `static/`:
  - `index.html`: Interfaz web responsiva con Chart.js y Phosphor Icons fijados por versión e integridad SRI.
  - `styles.css`: Estilos Liquid Glass UI adaptados a escritorio y móvil.
  - `app.js`: Delegación de eventos segura, sanitización de URLs/HTML, filtros coordinados por categoría/colección/promoción y gráficas escalonadas de precio y stock.
- `data/`:
  - `sony_tracker.db`: Base de datos SQLite local.
  - `banners/`: Imágenes de campañas descargadas localmente.
- `iniciar_servidor.bat` / `run.bat`: Accesos directos para iniciar el servidor en Windows.

## Requisitos

No requiere paquetes externos (`requirements.txt` solo usa biblioteca estándar de Python 3).

## Cómo Iniciar la Aplicación

1. Haz doble clic en `iniciar_servidor.bat` (o ejecuta `python server.py` en una terminal).
2. Abre en tu navegador:
   `http://localhost:8080/`
