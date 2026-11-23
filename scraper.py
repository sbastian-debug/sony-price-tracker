import urllib.request
import urllib.parse
import json
import gzip
import re
import os
import hashlib
from datetime import datetime
from database import (
    init_db,
    start_sync,
    finish_sync,
    save_or_update_product,
    save_campaign_with_banners,
    DB_PATH
)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/html, */*',
    'Accept-Encoding': 'gzip, deflate'
}

BANNERS_DIR = os.path.join(os.path.dirname(__file__), 'data', 'banners')

def fetch_url(url, is_json=False):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
        if resp.info().get('Content-Encoding') == 'gzip' or raw[:2] == b'\x1f\x8b':
            content = gzip.decompress(raw)
        else:
            content = raw
        text = content.decode('utf-8', errors='ignore')
        if is_json:
            return json.loads(text)
        return text

def download_image(img_url):
    """Descarga una imagen de banner y la guarda localmente."""
    if not img_url:
        return None
    try:
        os.makedirs(BANNERS_DIR, exist_ok=True)
        ext = os.path.splitext(urllib.parse.urlparse(img_url).path)[1]
        if not ext or len(ext) > 5:
            ext = '.jpg'
        
        file_hash = hashlib.md5(img_url.encode('utf-8')).hexdigest()
        local_filename = f"banner_{file_hash}{ext}"
        local_path = os.path.join(BANNERS_DIR, local_filename)

        if not os.path.exists(local_path):
            req = urllib.request.Request(img_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                with open(local_path, 'wb') as f:
                    f.write(resp.read())
        
        return f"/data/banners/{local_filename}"
    except Exception as e:
        print(f"Error descargando imagen {img_url}: {e}")
        return None

def clean_html_text(html_str):
    if not html_str:
        return ""
    clean = re.sub(r'<[^>]+>', ' ', html_str)
    clean = ' '.join(clean.split())
    return clean

def scrape_products(sync_id=None, db_path=DB_PATH):
    """
    Extrae todos los productos de Sony Store Bolivia.
    Inspecciona todas las variantes (SKUs) de cada producto para calcular
    de manera precisa el stock real y el mejor precio activo disponible.
    Registra cualquier cambio de precio y productos que se acaban de agotar.
    """
    print("Iniciando extracción detallada de productos y verificación de stock...")
    start = 0
    step = 50
    total_saved = 0
    total_in_stock = 0
    total_out_of_stock = 0
    cambios_detectados = []
    agotados_detectados = []

    while True:
        end = start + step - 1
        url = f"https://store.sony.com.bo/api/catalog_system/pub/products/search?_from={start}&_to={end}"
        print(f"  Consultando lote {start} a {end}...")

        try:
            products = fetch_url(url, is_json=True)
        except Exception as e:
            print(f"  Error en lote {start}-{end}: {e}")
            break

        if not products or len(products) == 0:
            print("  Fin de catálogo alcanzado.")
            break

        for p in products:
            try:
                prod_id = str(p.get('productId'))
                prod_name = p.get('productName', 'Sin nombre')
                
                cats = p.get('categories', [])
                cat_name = 'General'
                if cats:
                    cat_parts = [c for c in cats[0].split('/') if c]
                    cat_name = cat_parts[0] if cat_parts else 'General'

                link_text = p.get('linkText', '')
                prod_url = f"https://store.sony.com.bo/{link_text}/p" if link_text else ""

                items = p.get('items', [])
                
                available_variants = []
                unavailable_variants = []

                # Analizar CADA item / color / SKU del producto
                for it in items:
                    it_sku = str(it.get('itemId', ''))
                    it_img = it.get('images', [{}])[0].get('imageUrl', '') if it.get('images') else ''
                    
                    for s in it.get('sellers', []):
                        offer = s.get('commertialOffer', {})
                        qty = int(offer.get('AvailableQuantity', 0))
                        price = float(offer.get('Price', 0.0))
                        list_price = float(offer.get('ListPrice', price))

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
                    # El producto tiene stock en al menos una variante
                    best = min(available_variants, key=lambda x: x['price'])
                    available = True
                    total_qty = sum(x['qty'] for x in available_variants)
                    price = best['price']
                    list_price = best['list_price']
                    sku = best['sku']
                    img_url = best['img_url']
                    total_in_stock += 1
                elif unavailable_variants:
                    # Todas las variantes están sin stock, pero hay un precio de referencia conocido
                    best = min(unavailable_variants, key=lambda x: x['price'])
                    available = False
                    total_qty = 0
                    price = best['price']
                    list_price = best['list_price']
                    sku = best['sku']
                    img_url = best['img_url']
                    total_out_of_stock += 1
                else:
                    # Sin stock y precio 0 en todas las variantes
                    available = False
                    total_qty = 0
                    price = 0.0
                    list_price = 0.0
                    sku = items[0].get('itemId', '') if items else ''
                    img_url = items[0].get('images', [{}])[0].get('imageUrl', '') if items and items[0].get('images') else ''
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
                    'descripcion': p.get('description', ''),
                    'precio': price,
                    'precio_lista': list_price,
                    'descuento_porcentaje': discount,
                    'disponible': available,
                    'stock': total_qty
                }

                cambio, agotado = save_or_update_product(prod_record, sync_id=sync_id, db_path=db_path)
                if cambio:
                    cambios_detectados.append(cambio)
                    print(f"  🔔 [CAMBIO DE PRECIO DETECTADO]: {prod_name[:40]} | Antes: Bs. {cambio['precio_anterior']} -> Ahora: Bs. {cambio['precio_nuevo']} (Dif: Bs. {cambio['diferencia']})")

                if agotado:
                    agotados_detectados.append(agotado)
                    print(f"  ⚠️ [PRODUCTO AGOTADO]: {prod_name[:40]} | Antes tenía {agotado['stock_anterior']} unid.")

                total_saved += 1
            except Exception as pe:
                print(f"Error procesando producto {p.get('productId')}: {pe}")

        start += step

    print(f"Extracción finalizada. Total: {total_saved} (En Stock: {total_in_stock}, Agotados: {total_out_of_stock}) | Cambios de precio: {len(cambios_detectados)} | Nuevos agotados: {len(agotados_detectados)}")
    return total_saved, total_in_stock, total_out_of_stock, cambios_detectados, agotados_detectados

def scrape_campaigns_and_banners(db_path=DB_PATH):
    """Extrae las promociones del carrusel y los banners imperdibles de la portada."""
    print("Iniciando extracción de campañas y banners...")
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

    # 1. BANNERS DEL SLIDER PRINCIPAL
    slider = state_json.get('store.home/general-apps-slider-home#main', {})
    elements = slider.get('content', {}).get('elements', [])
    print(f"Banners principales encontrados en el slider: {len(elements)}")

    for i, el in enumerate(elements):
        try:
            content_html = el.get('contentHTML', '')
            img_dsk = el.get('imageUrlDsk')
            redirect = el.get('imageRedirect', '')
            if redirect and not redirect.startswith('http'):
                redirect = f"https://store.sony.com.bo{redirect}"

            pre_header_match = re.search(r'class=\"[^\"]*pre-header[^\"]*\"[^>]*>(.*?)</div>', content_html, re.DOTALL)
            title_match = re.search(r'class=\"[^\"]*title[^\"]*\"[^>]*>(.*?)</div>', content_html, re.DOTALL)
            desc_match = re.search(r'class=\"[^\"]*description[^\"]*\"[^>]*>(.*?)</div>', content_html, re.DOTALL)

            pre_header = clean_html_text(pre_header_match.group(1)) if pre_header_match else "OFERTA ESPECIAL"
            title = clean_html_text(title_match.group(1)) if title_match else f"Promoción Sony #{i+1}"
            desc = clean_html_text(desc_match.group(1)) if desc_match else ""

            rango_fechas = pre_header if any(m in pre_header.upper() for m in ["DEL", "NOVIEMBRE", "DICIEMBRE", "HASTA"]) else datetime.now().strftime("%B %Y")
            local_banner_path = download_image(img_dsk)
            clave_campana = hashlib.md5(f"{title}_{pre_header}_{img_dsk}".encode('utf-8')).hexdigest()

            camp_data = {
                'titulo': title,
                'pre_header': pre_header,
                'descripcion': desc,
                'rango_fechas': rango_fechas,
                'clave_unica': clave_campana
            }

            banners = [{
                'tipo': 'desktop',
                'url_remota': img_dsk,
                'archivo_local': local_banner_path,
                'enlace_redireccion': redirect,
                'texto_html': content_html
            }]

            save_campaign_with_banners(camp_data, banners, db_path=db_path)
            campaigns_saved += 1
            print(f"  [Slider Guardado]: {title} ({rango_fechas})")
        except Exception as e:
            print(f"Error procesando banner de slider {i}: {e}")

    # 2. BANNERS DE LA SECCIÓN "TE PRESENTAMOS NUESTROS IMPERDIBLES"
    try:
        for block_idx in range(1, 10):
            img_key = f"store.home/flex-layout.row#nuevos-lanzamientos/flex-layout.col#nuevos-lanzamientos/flex-layout.row#nuevos-lanzamientos-slider-container/slider-layout#nuevos-lanzamientos-slider/flex-layout.col#nuevos-lanzamientos-slider-block{block_idx}/image#nuevos-lanzamientos-slider-image-block{block_idx}"
            text_key = f"store.home/flex-layout.row#nuevos-lanzamientos/flex-layout.col#nuevos-lanzamientos/flex-layout.row#nuevos-lanzamientos-slider-container/slider-layout#nuevos-lanzamientos-slider/flex-layout.col#nuevos-lanzamientos-slider-block{block_idx}/rich-text#nuevos-lanzamientos-slider-text1-block{block_idx}"

            img_obj = state_json.get(img_key, {})
            text_obj = state_json.get(text_key, {})

            if not img_obj and not text_obj:
                continue

            content_img = img_obj.get('content', {}) or img_obj.get('props', {})
            content_text = text_obj.get('content', {}) or text_obj.get('props', {})

            img_url = content_img.get('src')
            link_url = content_img.get('link', {}).get('url', '')
            if link_url and not link_url.startswith('http'):
                link_url = f"https://store.sony.com.bo{link_url}"

            raw_text = content_text.get('text', '')
            clean_txt = raw_text.replace('\n', ' -- ').strip()

            if img_url:
                local_path = download_image(img_url)
                first_line = raw_text.split('\n')[0].strip() if raw_text else f"Imperdible #{block_idx}"
                desc_line = clean_html_text(raw_text)

                sub_camp = {
                    'titulo': first_line,
                    'pre_header': "IMPERDIBLES DEL MES",
                    'descripcion': desc_line,
                    'rango_fechas': datetime.now().strftime("%B %Y"),
                    'clave_unica': hashlib.md5(f"{first_line}_{img_url}".encode('utf-8')).hexdigest()
                }
                save_campaign_with_banners(sub_camp, [{
                    'tipo': 'imperdibles',
                    'url_remota': img_url,
                    'archivo_local': local_path,
                    'enlace_redireccion': link_url,
                    'texto_html': clean_txt
                }], db_path=db_path)
                campaigns_saved += 1
                print(f"  [Imperdible Guardado]: {first_line}")

    except Exception as ie:
        print(f"Error procesando sección imperdibles: {ie}")

    print(f"Total campañas y banners archivados: {campaigns_saved}")
    return campaigns_saved

def run_full_sync():
    """Ejecuta la sincronización completa de productos, precios y banners."""
    init_db()
    sync_id = start_sync()
    try:
        total_prods, in_stock, out_of_stock, cambios, agotados = scrape_products(sync_id=sync_id)
        total_camps = scrape_campaigns_and_banners()
        finish_sync(
            sync_id, 
            total_prods, 
            len(cambios), 
            len(agotados), 
            json.dumps({"cambios": cambios, "agotados": agotados}, ensure_ascii=False)
        )
        return {
            "sync_id": sync_id,
            "estado": "completado",
            "productos_procesados": total_prods,
            "cambios_detectados": len(cambios),
            "agotados_detectados": len(agotados),
            "cambios": cambios,
            "agotados": agotados,
            "campanas_archivadas": total_camps,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        finish_sync(sync_id, 0, 0, 0, json.dumps({"error": str(e)}), estado='error')
        raise

if __name__ == '__main__':
    run_full_sync()
