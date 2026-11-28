import urllib.request
import urllib.parse
import json
import gzip
import zlib
import re
import os
import time
import hashlib
from datetime import datetime
from database import (
    init_db,
    start_sync,
    finish_sync,
    save_or_update_product,
    save_campaign_with_banners,
    sync_campaigns_active_state,
    prune_inactive_collections,
    DB_PATH
)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/html, */*',
    'Accept-Encoding': 'gzip, deflate'
}

BANNERS_DIR = os.path.join(os.path.dirname(__file__), 'data', 'banners')
ALLOWED_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
CONTENT_TYPE_EXT_MAP = {
    'image/jpeg': '.jpg',
    'image/pjpeg': '.jpg',
    'image/jpg': '.jpg',
    'image/png': '.png',
    'image/webp': '.webp',
    'image/gif': '.gif'
}
MAX_FETCH_BYTES = 20 * 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024

def is_safe_http_url(url):
    """Valida que una URL use estrictamente esquema HTTP/HTTPS y host válido."""
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urllib.parse.urlparse(url.strip())
        return parsed.scheme.lower() in ('http', 'https') and bool(parsed.netloc)
    except Exception:
        return False

def normalize_sony_url(url):
    """Normaliza URLs relativas de Sony y descarta esquemas inseguros (ej. javascript:)."""
    if not url or not isinstance(url, str):
        return ''
    cleaned = url.strip()
    if cleaned.startswith('//'):
        cleaned = f"https:{cleaned}"
    elif cleaned.startswith('/'):
        cleaned = f"https://store.sony.com.bo{cleaned}"
    return cleaned if is_safe_http_url(cleaned) else ''

def fetch_url(url, is_json=False, max_bytes=MAX_FETCH_BYTES):
    if not is_safe_http_url(url):
        raise ValueError(f"URL remota inválida o bloqueada: {url}")
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ValueError(f"Respuesta remota excede el tamaño máximo permitido ({max_bytes} bytes)")
        encoding = (resp.info().get('Content-Encoding') or '').lower()
        if 'gzip' in encoding or raw[:2] == b'\x1f\x8b':
            content = gzip.decompress(raw)
        elif 'deflate' in encoding:
            try:
                content = zlib.decompress(raw)
            except zlib.error:
                content = zlib.decompress(raw, -zlib.MAX_WBITS)
        else:
            content = raw
        text = content.decode('utf-8', errors='ignore')
        if is_json:
            return json.loads(text)
        return text

def download_image(img_url):
    """Descarga una imagen raster segura de banner y la guarda localmente."""
    safe_url = normalize_sony_url(img_url)
    if not safe_url:
        return None
    try:
        os.makedirs(BANNERS_DIR, exist_ok=True)
        raw_ext = os.path.splitext(urllib.parse.urlparse(safe_url).path)[1].lower()
        ext = raw_ext if raw_ext in ALLOWED_IMAGE_EXTS else None

        req = urllib.request.Request(safe_url, headers=HEADERS)
        file_hash = hashlib.md5(safe_url.encode('utf-8')).hexdigest()

        # Verificar primero si ya existe en caché local con alguna extensión permitida
        if ext:
            cached_name = f"banner_{file_hash}{ext}"
            cached_path = os.path.join(BANNERS_DIR, cached_name)
            if os.path.exists(cached_path):
                return f"/data/banners/{cached_name}"

        with urllib.request.urlopen(req, timeout=15) as resp:
            ctype = (resp.info().get('Content-Type') or '').split(';')[0].strip().lower()
            if ctype and ctype not in CONTENT_TYPE_EXT_MAP:
                print(f"Bloqueado Content-Type no seguro en imagen ({ctype}): {safe_url}")
                return None

            final_ext = CONTENT_TYPE_EXT_MAP.get(ctype) or ext
            if final_ext not in ALLOWED_IMAGE_EXTS:
                return None

            data = resp.read(MAX_IMAGE_BYTES + 1)
            if len(data) > MAX_IMAGE_BYTES:
                print(f"Imagen excede límite de {MAX_IMAGE_BYTES} bytes: {safe_url}")
                return None

            local_filename = f"banner_{file_hash}{final_ext}"
            local_path = os.path.join(BANNERS_DIR, local_filename)
            if not os.path.exists(local_path):
                with open(local_path, 'wb') as f:
                    f.write(data)

            return f"/data/banners/{local_filename}"
    except Exception as e:
        print(f"Error descargando imagen {safe_url}: {e}")
        return None

def clean_html_text(html_str):
    if not html_str:
        return ""
    clean = re.sub(r'<[^>]+>', ' ', html_str)
    clean = ' '.join(clean.split())
    return clean

def _build_sku_lookup(raw_products):
    """Construye mapa SKU -> metadatos del producto para resolver BuyTogether y GiftSkuIds."""
    sku_map = {}
    for p in raw_products:
        pid = str(p.get('productId', '')).strip()
        pname = (p.get('productName') or '').strip()
        link_text = (p.get('linkText') or '').strip().lstrip('/')
        purl = normalize_sony_url(f"https://store.sony.com.bo/{link_text}/p" if link_text else "")
        for it in (p.get('items') or []):
            sku_id = str(it.get('itemId', '')).strip()
            if sku_id:
                sku_map[sku_id] = {
                    'sku': sku_id,
                    'product_id': pid,
                    'nombre': pname or f"SKU {sku_id}",
                    'url_producto': purl
                }
    return sku_map

def _extract_offer_promos(items, sku_map):
    """Extrae PromotionTeasers/Teasers, GiftSkuIds y BuyTogether sin duplicados."""
    teasers = []
    seen_teasers = set()
    regalos = []
    seen_regalos = set()
    buy_together = []
    seen_bt = set()

    for it in items:
        for s in (it.get('sellers') or []):
            offer = s.get('commertialOffer', {}) or {}

            # PromotionTeasers (formato limpio de VTEX)
            promo_list = offer.get('PromotionTeasers') or []
            for t in promo_list:
                if not isinstance(t, dict):
                    continue
                t_name = str(t.get('Name') or '').strip()
                cond = t.get('Conditions') or {}
                min_qty = int(cond.get('MinimumQuantity', 1) or 1)
                if t_name and (t_name, min_qty) not in seen_teasers:
                    seen_teasers.add((t_name, min_qty))
                    teasers.append({'name': t_name, 'min_qty': min_qty})

            # Fallback a Teasers si PromotionTeasers no trajo datos
            if not promo_list:
                for t in (offer.get('Teasers') or []):
                    if not isinstance(t, dict):
                        continue
                    t_name = str(t.get('<Name>k__BackingField') or t.get('Name') or '').strip()
                    cond = t.get('<Conditions>k__BackingField') or t.get('Conditions') or {}
                    min_qty = int(cond.get('<MinimumQuantity>k__BackingField') or cond.get('MinimumQuantity') or 1)
                    if t_name and (t_name, min_qty) not in seen_teasers:
                        seen_teasers.add((t_name, min_qty))
                        teasers.append({'name': t_name, 'min_qty': min_qty})

            # GiftSkuIds (Regalos gratis con compra)
            for gid in (offer.get('GiftSkuIds') or []):
                gsid = str(gid).strip()
                if gsid and gsid not in seen_regalos:
                    seen_regalos.add(gsid)
                    regalos.append(sku_map.get(gsid, {'sku': gsid, 'product_id': '', 'nombre': f"Regalo SKU {gsid}", 'url_producto': ''}))

            # BuyTogether (Combínalos / packs sugeridos)
            for btid in (offer.get('BuyTogether') or []):
                bsid = str(btid).strip()
                if bsid and bsid not in seen_bt:
                    seen_bt.add(bsid)
                    buy_together.append(sku_map.get(bsid, {'sku': bsid, 'product_id': '', 'nombre': f"Producto SKU {bsid}", 'url_producto': ''}))

    return teasers, regalos, buy_together

def _get_active_homepage_collection_slugs():
    """Obtiene los slugs de colecciones activas enlazadas hoy desde el slider principal de portada."""
    slugs = set()
    try:
        html = fetch_url('https://store.sony.com.bo/')
        for s in re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL):
            if 'general-apps-slider-home' in s:
                state_json = json.loads(s.strip())
                slider = state_json.get('store.home/general-apps-slider-home#main', {}) or {}
                for elem in ((slider.get('content') or {}).get('elements') or []):
                    raw_links = [elem.get('imageRedirect', '')]
                    raw_links.extend(re.findall(r'href=["\']([^"\']+)["\']', elem.get('contentHTML', '') or ''))
                    for rl in raw_links:
                        norm = normalize_sony_url(rl)
                        if not norm:
                            continue
                        path = urllib.parse.urlparse(norm).path.strip('/').lower()
                        if path and '/' not in path:
                            slugs.add(path)
                break
    except Exception as e:
        print(f"Aviso detectando colecciones activas de portada: {e}")
    return slugs

def scrape_products(sync_id=None, db_path=DB_PATH):
    """
    Extrae todos los productos de Sony Store Bolivia.
    Inspecciona variantes (SKUs), stock real, colecciones activas, teasers de promoción, regalos y BuyTogether.
    Registra variaciones de precio, recién agotados y reabastecidos.
    """
    print("Iniciando extracción detallada de productos, colecciones activas, promociones y stock...")
    start = 0
    step = 50
    raw_products = []

    while True:
        end = start + step - 1
        url = f"https://store.sony.com.bo/api/catalog_system/pub/products/search?_from={start}&_to={end}"
        print(f"  Consultando lote {start} a {end}...")

        products = None
        last_err = None
        for attempt in range(2):
            try:
                products = fetch_url(url, is_json=True)
                last_err = None
                break
            except Exception as e:
                last_err = e
                print(f"  Error en lote {start}-{end} (intento {attempt + 1}): {e}")
                if attempt == 0:
                    time.sleep(1.0)

        if last_err is not None:
            raise RuntimeError(f"Error de red consultando lote {start}-{end}: {last_err}")

        if not products or len(products) == 0:
            print("  Fin de catálogo alcanzado.")
            break

        raw_products.extend(products)
        start += step

    active_collection_names = _get_active_homepage_collection_slugs()
    for rp in raw_products:
        for hname in (rp.get('clusterHighlights') or {}).values():
            clean_h = str(hname).strip().lower()
            if clean_h:
                active_collection_names.add(clean_h)
    print(f"  Colecciones/highlights activos detectados en tienda: {sorted(active_collection_names)}")

    sku_map = _build_sku_lookup(raw_products)
    total_saved = 0
    total_in_stock = 0
    total_out_of_stock = 0
    cambios_detectados = []
    agotados_detectados = []
    reabastecidos_detectados = []

    for p in raw_products:
        try:
            prod_id = str(p.get('productId', '')).strip()
            if not prod_id:
                continue
            prod_name = (p.get('productName') or 'Sin nombre').strip()
            
            cats = p.get('categories', [])
            cat_name = 'General'
            if cats and isinstance(cats[0], str):
                cat_parts = [c.strip() for c in cats[0].split('/') if c.strip()]
                cat_name = cat_parts[0] if cat_parts else 'General'

            link_text = (p.get('linkText') or '').strip().lstrip('/')
            prod_url = normalize_sony_url(f"https://store.sony.com.bo/{link_text}/p" if link_text else "")

            # Conservar únicamente colecciones activas (portada actual o highlights vigentes)
            colecciones = [
                {'id': str(cid).strip(), 'name': str(cname).strip()}
                for cid, cname in (p.get('productClusters') or {}).items()
                if str(cid).strip() and str(cname).strip() and str(cname).strip().lower() in active_collection_names
            ]
            highlights = [
                {'id': str(hid).strip(), 'name': str(hname).strip()}
                for hid, hname in (p.get('clusterHighlights') or {}).items()
                if str(hid).strip() and str(hname).strip()
            ]

            items = p.get('items', []) or []
            teasers, regalos, buy_together = _extract_offer_promos(items, sku_map)

            available_variants = []
            unavailable_variants = []

            # Analizar CADA item / color / SKU del producto
            for it in items:
                it_sku = str(it.get('itemId', '')).strip()
                imgs = it.get('images') or []
                raw_it_img = imgs[0].get('imageUrl', '') if imgs and isinstance(imgs[0], dict) else ''
                it_img = normalize_sony_url(raw_it_img)
                
                for s in (it.get('sellers') or []):
                    offer = s.get('commertialOffer', {}) or {}
                    qty = max(0, int(offer.get('AvailableQuantity', 0) or 0))
                    price = float(offer.get('Price', 0.0) or 0.0)
                    list_price = float(offer.get('ListPrice', price) or price)

                    variant_info = {
                        'sku': it_sku,
                        'img_url': it_img,
                        'price': price,
                        'list_price': list_price,
                        'qty': qty
                    }

                    if qty > 0 and price > 0:
                        available_variants.append(variant_info)
                    elif price > 0:
                        unavailable_variants.append(variant_info)

            if available_variants:
                best = min(available_variants, key=lambda x: x['price'])
                available = True
                total_qty = sum(x['qty'] for x in available_variants)
                price = best['price']
                list_price = best['list_price']
                sku = best['sku']
                img_url = best['img_url']
                total_in_stock += 1
            elif unavailable_variants:
                best = min(unavailable_variants, key=lambda x: x['price'])
                available = False
                total_qty = 0
                price = best['price']
                list_price = best['list_price']
                sku = best['sku']
                img_url = best['img_url']
                total_out_of_stock += 1
            else:
                available = False
                total_qty = 0
                price = 0.0
                list_price = 0.0
                sku = str(items[0].get('itemId', '')).strip() if items else ''
                first_imgs = (items[0].get('images') or []) if items else []
                raw_first_img = first_imgs[0].get('imageUrl', '') if first_imgs and isinstance(first_imgs[0], dict) else ''
                img_url = normalize_sony_url(raw_first_img)
                total_out_of_stock += 1

            discount = 0.0
            if available and list_price > price and price > 0:
                discount = round((1.0 - (price / list_price)) * 100, 1)

            prod_record = {
                'id': prod_id,
                'sku': sku,
                'nombre': prod_name,
                'categoria': cat_name,
                'url_producto': prod_url,
                'imagen_url': img_url,
                'descripcion': p.get('description', '') or '',
                'precio': price,
                'precio_lista': list_price,
                'descuento_porcentaje': discount,
                'disponible': available,
                'stock': total_qty,
                'colecciones': colecciones,
                'highlights': highlights,
                'teasers': teasers,
                'regalos': regalos,
                'buy_together': buy_together
            }

            cambio, agotado, reabastecido = save_or_update_product(prod_record, sync_id=sync_id, db_path=db_path)
            if cambio:
                cambios_detectados.append(cambio)
                print(f"  🔔 [CAMBIO DE PRECIO DETECTADO]: {prod_name[:40]} | Antes: Bs. {cambio['precio_anterior']} -> Ahora: Bs. {cambio['precio_nuevo']} (Dif: Bs. {cambio['diferencia']})")

            if agotado:
                agotados_detectados.append(agotado)
                print(f"  ⚠️ [PRODUCTO AGOTADO]: {prod_name[:40]} | Antes tenía {agotado['stock_anterior']} unid.")

            if reabastecido:
                reabastecidos_detectados.append(reabastecido)
                print(f"  🎉 [PRODUCTO CON STOCK REPUESTO]: {prod_name[:40]} | Nuevo stock: {reabastecido['stock_nuevo']} unid.")

            total_saved += 1
        except Exception as pe:
            print(f"Error procesando producto {p.get('productId')}: {pe}")

    prune_inactive_collections(active_collection_names, db_path=db_path)
    print(f"Extracción finalizada. Total: {total_saved} (En Stock: {total_in_stock}, Agotados: {total_out_of_stock}) | Cambios de precio: {len(cambios_detectados)} | Nuevos agotados: {len(agotados_detectados)} | Reabastecidos: {len(reabastecidos_detectados)}")
    return total_saved, total_in_stock, total_out_of_stock, cambios_detectados, agotados_detectados, reabastecidos_detectados

def _extract_slider_elements(elements, default_pre_header, label_tag, db_path, active_keys):
    """Guarda banners de un componente general-apps-slider-home (portada o secret-sale)."""
    saved = 0
    for i, el in enumerate(elements or []):
        try:
            content_html = el.get('contentHTML', '') or ''
            img_dsk = normalize_sony_url(el.get('imageUrlDsk'))
            img_mob = normalize_sony_url(el.get('imageUrlMob'))
            if not img_dsk and not img_mob:
                continue

            redirect = normalize_sony_url(el.get('imageRedirect', ''))

            pre_header_match = re.search(r'class=\"[^\"]*pre-header[^\"]*\"[^>]*>(.*?)</div>', content_html, re.DOTALL)
            title_match = re.search(r'class=\"[^\"]*title[^\"]*\"[^>]*>(.*?)</div>', content_html, re.DOTALL)
            desc_match = re.search(r'class=\"[^\"]*description[^\"]*\"[^>]*>(.*?)</div>', content_html, re.DOTALL)

            pre_header = clean_html_text(pre_header_match.group(1)) if pre_header_match else default_pre_header
            if not pre_header:
                pre_header = default_pre_header
            title = clean_html_text(title_match.group(1)) if title_match else f"{default_pre_header} #{i+1}"
            desc = clean_html_text(desc_match.group(1)) if desc_match else ""

            rango_fechas = pre_header if any(m in pre_header.upper() for m in ["DEL", "NOVIEMBRE", "DICIEMBRE", "HASTA"]) else datetime.now().strftime("%B %Y")
            main_img = img_dsk or img_mob
            clave_campana = hashlib.md5(f"{title}_{pre_header}_{main_img}".encode('utf-8')).hexdigest()

            banners = []
            if img_dsk:
                banners.append({
                    'tipo': 'desktop',
                    'url_remota': img_dsk,
                    'archivo_local': download_image(img_dsk) or '',
                    'enlace_redireccion': redirect,
                    'texto_html': clean_html_text(content_html)
                })
            if img_mob and img_mob != img_dsk:
                banners.append({
                    'tipo': 'mobile',
                    'url_remota': img_mob,
                    'archivo_local': download_image(img_mob) or '',
                    'enlace_redireccion': redirect,
                    'texto_html': clean_html_text(content_html)
                })

            camp_data = {
                'titulo': title,
                'pre_header': pre_header,
                'descripcion': desc,
                'rango_fechas': rango_fechas,
                'clave_unica': clave_campana
            }

            save_campaign_with_banners(camp_data, banners, db_path=db_path)
            active_keys.append(clave_campana)
            saved += 1
            print(f"  [{label_tag} Guardado]: {title} ({rango_fechas})")
        except Exception as e:
            print(f"Error procesando {label_tag} {i}: {e}")
    return saved

def _infer_promo_title(link_url, prefix, idx):
    """Genera un título legible desde una ruta promocional de Sony."""
    if link_url:
        try:
            path = urllib.parse.urlparse(link_url).path.strip('/')
            if path and path != 'p':
                slug = path.split('/')[0].replace('-', ' ').replace('_', ' ').strip()
                if slug:
                    return f"{prefix}: {slug.title()}"
        except Exception:
            pass
    return f"{prefix} #{idx}"

def _extract_image_list_block(sj, key, pre_header, desc_text, db_path, active_keys):
    """Guarda banners de un bloque list-context.image-list (cintillos superior/bancario)."""
    saved = 0
    block = sj.get(key, {}) or {}
    images = ((block.get('content') or block.get('props') or {}).get('images')) or []
    for idx, img_item in enumerate(images, start=1):
        try:
            img_dsk = normalize_sony_url(img_item.get('image'))
            img_mob = normalize_sony_url(img_item.get('mobileImage'))
            if not img_dsk and not img_mob:
                continue

            link_url = normalize_sony_url((img_item.get('link') or {}).get('url', ''))
            title = (img_item.get('title') or '').strip() or _infer_promo_title(link_url, pre_header.title(), idx)
            main_img = img_dsk or img_mob
            clave = hashlib.md5(f"{pre_header}_{main_img}_{link_url}".encode('utf-8')).hexdigest()

            banners = []
            if img_dsk:
                banners.append({
                    'tipo': 'cintillo',
                    'url_remota': img_dsk,
                    'archivo_local': download_image(img_dsk) or '',
                    'enlace_redireccion': link_url,
                    'texto_html': title
                })
            if img_mob and img_mob != img_dsk:
                banners.append({
                    'tipo': 'mobile',
                    'url_remota': img_mob,
                    'archivo_local': download_image(img_mob) or '',
                    'enlace_redireccion': link_url,
                    'texto_html': title
                })

            save_campaign_with_banners({
                'titulo': title,
                'pre_header': pre_header,
                'descripcion': desc_text,
                'rango_fechas': datetime.now().strftime("%B %Y"),
                'clave_unica': clave
            }, banners, db_path=db_path)
            active_keys.append(clave)
            saved += 1
            print(f"  [{pre_header} Guardado]: {title}")
        except Exception as e:
            print(f"Error procesando {pre_header} #{idx}: {e}")
    return saved

def scrape_campaigns_and_banners(db_path=DB_PATH):
    """Extrae slider principal, imperdibles, cintillos, Favoritos Sony, popup/cupones y Secret Sale."""
    print("Iniciando extracción integral de campañas y banners...")
    try:
        html = fetch_url('https://store.sony.com.bo/')
    except Exception as e:
        print(f"Error cargando portada: {e}")
        return 0

    scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
    state_json = None

    for s in scripts:
        if 'general-apps-slider-home' in s:
            try:
                state_json = json.loads(s.strip())
                break
            except Exception:
                pass

    if not state_json:
        print("No se encontró el bloque de datos de la portada.")
        return 0

    campaigns_saved = 0
    active_keys = []

    # 1. BANNERS DEL SLIDER PRINCIPAL
    slider = state_json.get('store.home/general-apps-slider-home#main', {}) or {}
    elements = (slider.get('content') or {}).get('elements', []) or []
    print(f"Banners principales encontrados en el slider: {len(elements)}")
    campaigns_saved += _extract_slider_elements(elements, "OFERTA ESPECIAL", "Slider", db_path, active_keys)

    # 2. BANNERS DE LA SECCIÓN "TE PRESENTAMOS NUESTROS IMPERDIBLES"
    try:
        for block_idx in range(1, 10):
            img_key = f"store.home/flex-layout.row#nuevos-lanzamientos/flex-layout.col#nuevos-lanzamientos/flex-layout.row#nuevos-lanzamientos-slider-container/slider-layout#nuevos-lanzamientos-slider/flex-layout.col#nuevos-lanzamientos-slider-block{block_idx}/image#nuevos-lanzamientos-slider-image-block{block_idx}"
            text_key = f"store.home/flex-layout.row#nuevos-lanzamientos/flex-layout.col#nuevos-lanzamientos/flex-layout.row#nuevos-lanzamientos-slider-container/slider-layout#nuevos-lanzamientos-slider/flex-layout.col#nuevos-lanzamientos-slider-block{block_idx}/rich-text#nuevos-lanzamientos-slider-text1-block{block_idx}"

            img_obj = state_json.get(img_key, {})
            text_obj = state_json.get(text_key, {})

            if not img_obj and not text_obj:
                continue

            content_img = img_obj.get('content', {}) or img_obj.get('props', {}) or {}
            content_text = text_obj.get('content', {}) or text_obj.get('props', {}) or {}

            img_url = normalize_sony_url(content_img.get('src'))
            link_url = normalize_sony_url((content_img.get('link') or {}).get('url', ''))

            raw_text = content_text.get('text', '') or ''
            clean_txt = clean_html_text(raw_text)

            if img_url:
                local_path = download_image(img_url)
                first_line = raw_text.split('\n')[0].strip() if raw_text else f"Imperdible #{block_idx}"
                desc_line = clean_html_text(raw_text)
                clave_imp = hashlib.md5(f"{first_line}_{img_url}".encode('utf-8')).hexdigest()

                sub_camp = {
                    'titulo': first_line,
                    'pre_header': "IMPERDIBLES DEL MES",
                    'descripcion': desc_line,
                    'rango_fechas': datetime.now().strftime("%B %Y"),
                    'clave_unica': clave_imp
                }
                save_campaign_with_banners(sub_camp, [{
                    'tipo': 'imperdibles',
                    'url_remota': img_url,
                    'archivo_local': local_path or '',
                    'enlace_redireccion': link_url,
                    'texto_html': clean_txt
                }], db_path=db_path)
                active_keys.append(clave_imp)
                campaigns_saved += 1
                print(f"  [Imperdible Guardado]: {first_line}")

    except Exception as ie:
        print(f"Error procesando sección imperdibles: {ie}")

    # 3. CINTILLOS PROMOCIONALES DE PORTADA (Superior y Bancario)
    campaigns_saved += _extract_image_list_block(
        state_json,
        'store.home/general-apps-conditional-show-block#home-banner-promotional/list-context.image-list#home-banner-promotional',
        'CINTILLO SUPERIOR',
        'Cintillo promocional destacado en la parte superior de Sony Store Bolivia.',
        db_path,
        active_keys,
    )
    campaigns_saved += _extract_image_list_block(
        state_json,
        'store.home/general-apps-conditional-show-block#home-banner-promotional-2/list-context.image-list#home-banner-promotional',
        'CINTILLO PROMOCIONAL',
        'Cintillo bancario / banners rotativos de beneficios en portada.',
        db_path,
        active_keys,
    )

    # 4. FAVORITOS SONY EN PORTADA
    for fav_idx in range(1, 8):
        fav_key = f"store.home/flex-layout.row#favoritos-sony-container/flex-layout.col#favoritos-sony-container/flex-layout.row#favoritos-sony-items/flex-layout.col#favoritos-sony-items-item{fav_idx}/image#favoritos-sony-items-image-item{fav_idx}"
        fav_obj = state_json.get(fav_key, {})
        if not fav_obj:
            continue
        c_fav = fav_obj.get('content', {}) or fav_obj.get('props', {}) or {}
        fav_img = normalize_sony_url(c_fav.get('src'))
        if not fav_img:
            continue
        fav_link = normalize_sony_url((c_fav.get('link') or {}).get('url', ''))
        fav_title = (c_fav.get('title') or c_fav.get('alt') or '').strip() or _infer_promo_title(fav_link, "Favorito Sony", fav_idx)
        clave_fav = hashlib.md5(f"favoritos_{fav_idx}_{fav_img}".encode('utf-8')).hexdigest()

        save_campaign_with_banners({
            'titulo': fav_title,
            'pre_header': 'FAVORITOS SONY',
            'descripcion': f'Banner destacado de la sección Favoritos Sony ({fav_link or "Portada"}).',
            'rango_fechas': datetime.now().strftime("%B %Y"),
            'clave_unica': clave_fav
        }, [{
            'tipo': 'favoritos',
            'url_remota': fav_img,
            'archivo_local': download_image(fav_img) or '',
            'enlace_redireccion': fav_link,
            'texto_html': fav_title
        }], db_path=db_path)
        active_keys.append(clave_fav)
        campaigns_saved += 1
        print(f"  [Favorito Guardado]: {fav_title}")

    # 5. POPUP PROMOCIONAL Y CUPÓN DE BIENVENIDA EN PORTADA
    try:
        modal_key = (
            'store.home/general-apps-conditional-show-block#custom-modal/'
            'general-apps-wrapper-select-country#custom-modal-country-available/'
            'general-apps-show-welcome-back#custom-modal/modal-trigger#custom-modal/'
            'modal-layout#custom-modal/modal-content#custom-modal/'
            'rich-text#custom-modal-content'
        )
        cupon_key = (
            'store.home/general-apps-conditional-show-block#custom-modal/'
            'general-apps-wrapper-select-country#custom-modal-country-available/'
            'general-apps-show-welcome-back#custom-modal/modal-trigger#custom-modal/'
            'modal-layout#custom-modal/modal-content#custom-modal/'
            'flex-layout.row#form-cupon-modal/flex-layout.col#form-cupon-modal/'
            'flex-layout.row#thank-you-message-form-newsletter-campaing/'
            'flex-layout.col#thank-you-message-form-newsletter-campaing/'
            'rich-text#cupon-text-thank-you-message-newsletter-campaing'
        )
        modal_text = ((state_json.get(modal_key, {}).get('content') or state_json.get(modal_key, {}).get('props') or {}).get('text')) or ''
        cupon_code = ((state_json.get(cupon_key, {}).get('content') or state_json.get(cupon_key, {}).get('props') or {}).get('text')) or ''

        md_banners = re.findall(r'\[!\[[^\]]*\]\(([^)]+)\)\]\(([^)]+)\)', modal_text)
        popup_banners = []
        for idx_p, (raw_img, raw_link) in enumerate(md_banners):
            p_img = normalize_sony_url(raw_img)
            if not p_img:
                continue
            p_link = normalize_sony_url(raw_link)
            popup_banners.append({
                'tipo': 'mobile' if ('375x' in p_img or idx_p == 0 and len(md_banners) > 1) else 'popup',
                'url_remota': p_img,
                'archivo_local': download_image(p_img) or '',
                'enlace_redireccion': p_link,
                'texto_html': clean_html_text(cupon_code or 'Popup Promocional')
            })
        if popup_banners:
            # Asegurar que el primer banner no-mobile sea portada si existe
            popup_banners.sort(key=lambda b: 1 if b['tipo'] == 'mobile' else 0)
            clave_popup = hashlib.md5(f"popup_{popup_banners[0]['url_remota']}_{cupon_code}".encode('utf-8')).hexdigest()
            desc_popup = "Banner emergente de portada."
            if cupon_code:
                desc_popup += f" Cupón asociado en modal: {cupon_code.strip()}."
            save_campaign_with_banners({
                'titulo': _infer_promo_title(popup_banners[0]['enlace_redireccion'], "Popup Portada", 1),
                'pre_header': 'POPUP Y CUPÓN PORTADA',
                'descripcion': desc_popup,
                'rango_fechas': datetime.now().strftime("%B %Y"),
                'clave_unica': clave_popup
            }, popup_banners, db_path=db_path)
            active_keys.append(clave_popup)
            campaigns_saved += 1
            print(f"  [Popup Guardado]: {len(popup_banners)} imagen(es), cupón={cupon_code.strip()}")
    except Exception as pe:
        print(f"Error procesando popup/cupón de portada: {pe}")

    # 6. SLIDER EXCLUSIVO DE SECRET SALE (/secret-sale)
    try:
        ss_html = fetch_url('https://store.sony.com.bo/secret-sale')
        ss_scripts = re.findall(r'<script[^>]*>(.*?)</script>', ss_html, re.DOTALL)
        for s in ss_scripts:
            if 'general-apps-slider-home#promociones' in s:
                ss_json = json.loads(s.strip())
                ss_key = 'vtex.store@2.x:store.custom#secret-sale/flex-layout.row#orderBy-search/flex-layout.col#orderBy-search/general-apps-slider-home#promociones'
                ss_slider = ss_json.get(ss_key, {}) or {}
                ss_elems = (ss_slider.get('content') or {}).get('elements', []) or []
                print(f"Banners encontrados en /secret-sale: {len(ss_elems)}")
                campaigns_saved += _extract_slider_elements(ss_elems, "SECRET SALE", "Secret Sale", db_path, active_keys)
                break
    except Exception as se:
        print(f"Error procesando slider de Secret Sale: {se}")

    if active_keys:
        sync_campaigns_active_state(active_keys, db_path=db_path)

    print(f"Total campañas y banners archivados: {campaigns_saved}")
    return campaigns_saved

def run_full_sync():
    """Ejecuta la sincronización completa de productos, precios y banners."""
    init_db()
    sync_id = start_sync()
    try:
        total_prods, in_stock, out_of_stock, cambios, agotados, reabastecidos = scrape_products(sync_id=sync_id)
        total_camps = scrape_campaigns_and_banners()
        finish_sync(
            sync_id, 
            total_prods, 
            len(cambios), 
            len(agotados),
            len(reabastecidos),
            json.dumps({"cambios": cambios, "agotados": agotados, "reabastecidos": reabastecidos}, ensure_ascii=False)
        )
        return {
            "sync_id": sync_id,
            "estado": "completado",
            "productos_procesados": total_prods,
            "cambios_detectados": len(cambios),
            "agotados_detectados": len(agotados),
            "reabastecidos_detectados": len(reabastecidos),
            "cambios": cambios,
            "agotados": agotados,
            "reabastecidos": reabastecidos,
            "campanas_archivadas": total_camps,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        finish_sync(sync_id, 0, 0, 0, 0, json.dumps({"error": str(e)}), estado='error')
        raise

if __name__ == '__main__':
    run_full_sync()
