import urllib.request
import json

try:
    res = urllib.request.urlopen('http://127.0.0.1:8080/api/products?stock=all&sort=discount_desc')
    data = json.loads(res.read().decode('utf-8'))
    print(f"Total products returned: {len(data)}")
    if data:
        p = data[0]
        print(f"Product: {p.get('nombre')}")
        print(f"Stock: {p.get('stock')}")
        print(f"Disponible: {p.get('disponible')}")
        print(f"Precio Actual: {p.get('precio_actual')}")
        print(f"Recién Agotado: {p.get('recien_agotado')}")
        print(f"Es Mínimo Histórico: {p.get('es_minimo_historico')}")

    # Test product history endpoint
    p_id = data[0]['id']
    h_res = urllib.request.urlopen(f'http://127.0.0.1:8080/api/products/{p_id}/history')
    h_data = json.loads(h_res.read().decode('utf-8'))
    print(f"History entries for {p_id}: {len(h_data.get('historial', []))}")
    if h_data.get('historial'):
        print(f"First history sample: {h_data['historial'][0]}")

    print("ALL API CHECKS PASSED SUCCESSFULLY!")
except Exception as e:
    print(f"Error testing API: {e}")
