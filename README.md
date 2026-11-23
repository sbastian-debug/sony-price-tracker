# SonyBoliviaDB - Monitor de Precios Históricos, Combos & Archivo de Campañas

Aplicación completa inspirada en SteamDB con diseño **Liquid Glass UI (iOS)** para rastrear el catálogo completo de productos de **Sony Store Bolivia** (`store.sony.com.bo`), registrar el histórico de precios para detectar **mínimos históricos (All-Time Low)**, capturar promociones de tipo **"Compra junto y ahorra" (Combos)** y archivar **campañas publicitarias pasadas** e imperdibles con sus banners en alta resolución.

## Estructura del Proyecto

- `database.py`: Gestión de base de datos SQLite con tablas para productos, histórico de precios, campañas, banners, combos y opciones de bundle.
- `scraper.py`: Extractor automático que consulta los 404 productos, analiza las páginas de producto en busca de combos *"Compra junto y ahorra"* y descarga los banners publicitarios de la portada y la sección *"Te presentamos nuestros imperdibles"*.
- `server.py`: Servidor HTTP ligero y API REST local (puerto 8080) con endpoints para productos, historial, campañas y combos.
- `static/`:
  - `index.html`: Interfaz web con fondo refractivo líquido, navegación por pestañas iOS y ventanas modales de cristal.
  - `styles.css`: Estilos visuales con diseño Liquid Glass UI y fotos de productos en alta resolución.
  - `app.js`: Lógica interactiva de filtrado, selector dinámico de opciones de combo con cálculo de ahorro en vivo y gráficas con Chart.js.
- `data/`:
  - `sony_tracker.db`: Base de datos SQLite local con todos los productos, registros de precios, campañas y combos.
  - `banners/`: Imágenes de los banners promocionales descargadas en alta resolución.

## Cómo Iniciar la Aplicación

1. Abre una terminal en esta carpeta o ejecuta `run.bat`:
   ```bash
   python server.py
   ```
2. Abre tu navegador web en:
   ```
   http://localhost:8080
   ```

## Funcionalidades Principales

1. **Catálogo & Mínimos Históricos:**
   - Vitrina con fotos grandes de 220px (o vista lista espaciosa).
   - Cálculo automático del mínimo histórico registrado (insignia verde ⭐).
   - Filtros por categoría, búsqueda en tiempo real y orden por mayor descuento.
   - Gráfica interactiva temporal con curva líquida y línea de All-Time Low.

2. **Sección de Combos ("Compra junto y ahorra"):**
   - Detecta automáticamente los paquetes y ofertas cruzadas dentro de las fichas de producto (como el tocadiscos con vinilos exclusivos o televisores con barras de sonido).
   - Interfaz con selector de opciones complementarias que recalcula en tiempo real el precio total del combo y el dinero que ahorras.

3. **Campañas Publicitarias Pasadas & Banners Imperdibles:**
   - Archivo histórico de carruseles principales y la sección *"Te presentamos nuestros imperdibles"* (como cupones de descuento *Hit del Mes* y ofertas relámpago).
   - Recuadros organizados por fecha y estado de vigencia, con visualizador en alta resolución de los banners guardados.
