from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime
import os

app = FastAPI(title="MercadoLibre Scanner API", version="2.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuración
URLS = {
    "celulares": "https://listado.mercadolibre.cl/celulares-telefonia/celulares-smartphones/usado/celular_OrderId_PRICE_PublishedToday_YES_NoIndex_True",
    "notebooks": "https://listado.mercadolibre.cl/computacion/notebooks-accesorios/notebooks/usado/notebook_OrderId_PRICE_PublishedToday_YES_NoIndex_True"
}

PAGINAS_CONFIG = {
    "celulares": 3,
    "notebooks": 2
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'es-CL,es;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Cache-Control': 'max-age=0',
    'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"'
}

# Modelos
class Producto(BaseModel):
    id: str
    title: str
    price: str
    link: str
    image: str
    categoria: str
    timestamp: str
    fecha: str
    pagina: int

class ScanResponse(BaseModel):
    success: bool
    message: str
    total_productos: int
    celulares: List[Producto]
    notebooks: List[Producto]
    stats: Dict[str, int]
    timestamp: str

# Funciones
def extraer_titulo(item):
    """Extrae el título del item"""
    title = ""
    
    # Opción 1: Clase específica
    title_elem = item.find('h2', class_='ui-search-item__title')
    if title_elem:
        title = title_elem.get_text(strip=True)
    
    # Opción 2: Cualquier h2
    if not title:
        title_elem = item.find('h2')
        if title_elem:
            title = title_elem.get_text(strip=True)
    
    # Opción 3: Atributos del link
    if not title:
        link_elem = item.find('a', href=True)
        if link_elem:
            title = link_elem.get('title', '') or link_elem.get('aria-label', '')
    
    # Opción 4: Divs con "title"
    if not title:
        title_div = item.find('div', class_=re.compile('.*title.*', re.I))
        if title_div:
            title = title_div.get_text(strip=True)
    
    # Opción 5: Texto general
    if not title:
        all_text = item.get_text(strip=True)
        words = all_text.split()
        if len(' '.join(words[:10])) > 10:
            title = ' '.join(words[:15])
    
    return title

def verificar_pagina_existe(url):
    """Verifica si una página existe"""
    try:
        print(f"   🌐 Haciendo request a: {url[:100]}...")
        
        # Crear sesión con configuración explícita
        session = requests.Session()
        session.headers.update(HEADERS)
        
        response = session.get(url, timeout=10)
        print(f"   📊 Status Code: {response.status_code}")
        print(f"   📏 Response Length: {len(response.content)} bytes")
        print(f"   🔤 Content-Type: {response.headers.get('content-type', 'N/A')}")
        print(f"   🗜️ Content-Encoding: {response.headers.get('content-encoding', 'N/A')}")
        
        if response.status_code != 200:
            print(f"   ❌ Status code != 200")
            return False, 0
        
        # Verificar si el contenido está correctamente decodificado
        html_text = response.text
        print(f"   📝 HTML text length: {len(html_text)} chars")
        print(f"   📄 Primeros 200 chars: {html_text[:200]}")
        
        soup = BeautifulSoup(html_text, 'html.parser')
        items = soup.find_all('li', class_='ui-search-layout__item')
        if not items:
            items = soup.find_all('div', class_='ui-search-result')
        
        print(f"   🔍 Items encontrados: {len(items)}")
        
        # Verificar mensajes de error
        no_results = soup.find('div', class_='ui-search-rescue')
        if no_results:
            print(f"   ⚠️ Mensaje 'sin resultados' detectado: {no_results.get_text(strip=True)[:100]}")
        
        return len(items) > 0, len(items)
    except Exception as e:
        print(f"   ❌ Error verificando página: {e}")
        import traceback
        print(f"   {traceback.format_exc()}")
        return False, 0

def escanear_mercadolibre():
    """
    Escanea MercadoLibre y retorna TODOS los productos encontrados
    Sin guardar nada, sin comparaciones
    """
    celulares_lista = []
    notebooks_lista = []
    
    stats = {
        "celulares_total": 0,
        "notebooks_total": 0
    }
    
    print(f"\n{'='*60}")
    print(f"🔍 INICIANDO ESCANEO")
    print(f"{'='*60}\n")
    
    for categoria, url_base in URLS.items():
        print(f"\n{'='*60}")
        print(f"Escaneando: {categoria.upper()}")
        print(f"{'='*60}")
        
        productos_categoria = []
        num_paginas_max = PAGINAS_CONFIG.get(categoria, 1)
        pagina = 1
        
        while pagina <= num_paginas_max:
            if pagina == 1:
                url = url_base
            else:
                offset = (pagina - 1) * 50 + 1
                url = url_base.replace('_OrderId', f'_Desde_{offset}_OrderId')
            
            print(f"\n📄 Página {pagina}...")
            
            existe, num_items = verificar_pagina_existe(url)
            if not existe:
                print(f"   ⚠️ Página {pagina} no existe o no tiene productos")
                break
            
            print(f"   ✅ {num_items} items encontrados")
            
            try:
                response = requests.get(url, headers=HEADERS, timeout=15)
                if response.status_code != 200:
                    print(f"   ⚠️ Error {response.status_code}")
                    pagina += 1
                    continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                items = soup.find_all('li', class_='ui-search-layout__item')
                if not items:
                    items = soup.find_all('div', class_='ui-search-result')
                
                for item in items:
                    try:
                        # Extraer datos
                        title = extraer_titulo(item)
                        
                        link = ""
                        link_elem = item.find('a', href=True)
                        if link_elem:
                            link = link_elem['href']
                            if not link.startswith('http'):
                                link = 'https://www.mercadolibre.cl' + link
                        
                        price_text = "$ 0"
                        price_elem = item.find('span', class_='andes-money-amount__fraction')
                        if price_elem:
                            price_text = f"$ {price_elem.get_text(strip=True)}"
                        
                        image = ""
                        img_elem = item.find('img')
                        if img_elem:
                            image = img_elem.get('data-src') or img_elem.get('src') or ""
                        
                        product_id = ""
                        if link:
                            match = re.search(r'ML[A-Z]-?\d+', link)
                            if match:
                                product_id = match.group(0).replace('-', '')
                        
                        if title and link and product_id:
                            producto = {
                                "id": product_id,
                                "title": title,
                                "price": price_text,
                                "link": link,
                                "image": image,
                                "categoria": categoria,
                                "timestamp": datetime.now().strftime("%H:%M:%S"),
                                "fecha": datetime.now().strftime("%Y-%m-%d"),
                                "pagina": pagina
                            }
                            
                            productos_categoria.append(producto)
                            print(f"   ✅ [{product_id}]: {title[:50]}")
                        else:
                            print(f"   ⚠️ Producto incompleto - Title:{bool(title)} Link:{bool(link)} ID:{bool(product_id)}")
                    
                    except Exception as e:
                        print(f"   ❌ Error procesando item: {e}")
                        continue
            
            except Exception as e:
                print(f"   ❌ Error en página {pagina}: {e}")
            
            pagina += 1
        
        print(f"\n✅ {categoria}: {len(productos_categoria)} productos encontrados en {pagina-1} página(s)")
        
        # Guardar en la lista correspondiente
        if categoria == "celulares":
            celulares_lista = productos_categoria
            stats["celulares_total"] = len(productos_categoria)
        elif categoria == "notebooks":
            notebooks_lista = productos_categoria
            stats["notebooks_total"] = len(productos_categoria)
    
    total = len(celulares_lista) + len(notebooks_lista)
    
    print(f"\n{'='*60}")
    print(f"🎉 ESCANEO COMPLETADO")
    print(f"   📱 Celulares: {len(celulares_lista)}")
    print(f"   💻 Notebooks: {len(notebooks_lista)}")
    print(f"   📊 Total: {total}")
    print(f"{'='*60}\n")
    
    return celulares_lista, notebooks_lista, stats

# ENDPOINTS

@app.get("/")
def root():
    return {
        "app": "MercadoLibre Scanner API",
        "version": "2.0.0",
        "mode": "Stateless - Solo escaneo",
        "description": "Escanea y devuelve todos los productos. Sin memoria ni comparaciones.",
        "endpoints": {
            "GET /": "Esta información",
            "GET /health": "Health check",
            "POST /scan": "Escanear MercadoLibre y devolver todos los productos",
            "GET /docs": "Documentación interactiva (Swagger)"
        }
    }

@app.get("/health")
def health():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "mode": "stateless"
    }

@app.post("/scan", response_model=ScanResponse)
def scan_mercadolibre():
    """
    Escanea MercadoLibre y devuelve TODOS los productos encontrados
    
    No guarda nada, no hace comparaciones.
    La app es responsable de comparar con su cache local.
    """
    try:
        celulares, notebooks, stats = escanear_mercadolibre()
        
        return ScanResponse(
            success=True,
            message=f"Escaneo completado: {len(celulares)} celulares, {len(notebooks)} notebooks",
            total_productos=len(celulares) + len(notebooks),
            celulares=[Producto(**p) for p in celulares],
            notebooks=[Producto(**p) for p in notebooks],
            stats={
                "celulares": len(celulares),
                "notebooks": len(notebooks),
                "total": len(celulares) + len(notebooks)
            },
            timestamp=datetime.now().isoformat()
        )
    
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"\n❌ ERROR EN SCAN:")
        print(error_detail)
        raise HTTPException(
            status_code=500, 
            detail={
                "error": str(e),
                "traceback": error_detail
            }
        )

@app.get("/ping")
def ping():
    """Simple ping para mantener el servidor activo"""
    return {
        "status": "pong",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/debug/test-url")
def debug_test_url():
    """
    Prueba directa de las URLs para ver qué está pasando
    """
    resultados = {}
    
    for categoria, url in URLS.items():
        try:
            print(f"\n{'='*50}")
            print(f"🔍 Probando: {categoria}")
            print(f"URL: {url}")
            print(f"{'='*50}")
            
            response = requests.get(url, headers=HEADERS, timeout=15)
            
            print(f"Status Code: {response.status_code}")
            print(f"Content Length: {len(response.text)}")
            
            # Guardar snippet del HTML
            html_snippet = response.text[:1000]
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Buscar items de varias formas
            items_v1 = soup.find_all('li', class_='ui-search-layout__item')
            items_v2 = soup.find_all('div', class_='ui-search-result')
            
            # Buscar mensajes de error o sin resultados
            no_results = soup.find('div', class_='ui-search-rescue')
            error_msg = soup.find('div', class_='andes-message')
            
            print(f"Items v1: {len(items_v1)}")
            print(f"Items v2: {len(items_v2)}")
            print(f"No results div: {bool(no_results)}")
            print(f"Error message: {bool(error_msg)}")
            
            # Intentar extraer del primer item si existe
            primer_item = None
            items = items_v1 if items_v1 else items_v2
            
            if items:
                item = items[0]
                title_elem = item.find('h2')
                link_elem = item.find('a', href=True)
                
                primer_item = {
                    "tiene_h2": bool(title_elem),
                    "tiene_link": bool(link_elem),
                    "texto_h2": title_elem.get_text(strip=True)[:100] if title_elem else "NO ENCONTRADO",
                    "html_snippet": str(item)[:500]
                }
            
            resultados[categoria] = {
                "status_code": response.status_code,
                "content_length": len(response.text),
                "html_snippet": html_snippet,
                "items_v1_count": len(items_v1),
                "items_v2_count": len(items_v2),
                "tiene_no_results": bool(no_results),
                "tiene_error_msg": bool(error_msg),
                "primer_item": primer_item,
                "no_results_text": no_results.get_text(strip=True)[:200] if no_results else None,
                "error_msg_text": error_msg.get_text(strip=True)[:200] if error_msg else None
            }
            
        except Exception as e:
            import traceback
            resultados[categoria] = {
                "error": str(e),
                "traceback": traceback.format_exc()
            }
    
    return {
        "success": True,
        "resultados": resultados,
        "headers_usados": dict(HEADERS)
    }

@app.get("/debug/simple-request")
def debug_simple_request():
    """Petición más simple posible a MercadoLibre"""
    try:
        url = "https://listado.mercadolibre.cl/celulares-telefonia/celulares-smartphones/"
        
        # Petición super simple
        response = requests.get(url, timeout=10)
        
        soup = BeautifulSoup(response.text, 'html.parser')
        items = soup.find_all('li', class_='ui-search-layout__item')
        
        return {
            "url": url,
            "status": response.status_code,
            "items_encontrados": len(items),
            "html_length": len(response.text),
            "funciona": len(items) > 0
        }
    except Exception as e:
        return {
            "error": str(e)
        }

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
