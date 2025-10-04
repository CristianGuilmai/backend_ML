from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime
import os

app = FastAPI(title="MercadoLibre Scanner API", version="2.1.0")

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

# Headers simplificados (sin Accept-Encoding para evitar Brotli)
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'es-CL,es;q=0.9',
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
    """Extrae el título del item - MEJORADO del código local"""
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
    """Verifica si una página existe - COPIADO del código local"""
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        
        if response.status_code != 200:
            return False, 0
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        items = soup.find_all('li', class_='ui-search-layout__item')
        if not items:
            items = soup.find_all('div', class_='ui-search-result')
        
        if len(items) > 0:
            return True, len(items)
        
        no_results = soup.find('div', class_='ui-search-rescue')
        if no_results:
            return False, 0
        
        return False, 0
        
    except Exception as e:
        print(f"   ❌ Error verificando página: {e}")
        return False, 0

def escanear_mercadolibre():
    """
    Escanea MercadoLibre usando la LÓGICA del código local que funciona
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
            
            print(f"\n📄 Verificando página {pagina}...")
            
            existe, num_items = verificar_pagina_existe(url)
            
            if not existe:
                print(f"   ⚠️ Página {pagina} no existe o no tiene productos.")
                break
            
            print(f"   ✅ Página {pagina} existe con {num_items} items")
            print(f"   🔍 Procesando productos...")
            
            try:
                response = requests.get(url, headers=HEADERS, timeout=15)
                
                if response.status_code != 200:
                    print(f"   ⚠️ Error {response.status_code}, saltando página")
                    pagina += 1
                    continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                items = soup.find_all('li', class_='ui-search-layout__item')
                if not items:
                    items = soup.find_all('div', class_='ui-search-result')
                
                for item in items:
                    try:
                        # Extraer título usando la función mejorada
                        title = extraer_titulo(item)
                        
                        # Extraer link
                        link = ""
                        link_elem = item.find('a', href=True)
                        if link_elem:
                            link = link_elem['href']
                            if not link.startswith('http'):
                                link = 'https://www.mercadolibre.cl' + link
                        
                        # Extraer precio
                        price_text = "$ 0"
                        price_elem = item.find('span', class_='andes-money-amount__fraction')
                        if price_elem:
                            price_text = f"$ {price_elem.get_text(strip=True)}"
                        
                        # Extraer imagen
                        image = ""
                        img_elem = item.find('img')
                        if img_elem:
                            image = img_elem.get('data-src') or img_elem.get('src') or ""
                        
                        # Extraer ID
                        product_id = ""
                        if link:
                            match = re.search(r'ML[A-Z]-?\d+', link)
                            if match:
                                product_id = match.group(0).replace('-', '')
                        
                        # Debug de productos incompletos
                        if not title or not link or not product_id:
                            print(f"   ⚠️ Producto incompleto - Title:{bool(title)} Link:{bool(link)} ID:{bool(product_id)}")
                            if title:
                                print(f"      Title encontrado: {title[:50]}")
                            continue
                        
                        # Crear objeto producto
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
                    
                    except Exception as e:
                        print(f"   ❌ Error procesando item: {e}")
                        continue
            
            except requests.RequestException as e:
                print(f"   ❌ Error de conexión en página {pagina}: {e}")
                pagina += 1
                continue
            
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
        "version": "2.1.0",
        "mode": "Stateless - Solo escaneo",
        "description": "Escanea y devuelve todos los productos. Lógica mejorada del código local.",
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
    Usa la lógica del código local que funciona perfectamente
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
    return {
        "status": "pong",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/debug/test-url")
def debug_test_url():
    """Prueba directa de las URLs"""
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
            
            html_snippet = response.text[:1000]
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            items_v1 = soup.find_all('li', class_='ui-search-layout__item')
            items_v2 = soup.find_all('div', class_='ui-search-result')
            
            no_results = soup.find('div', class_='ui-search-rescue')
            error_msg = soup.find('div', class_='andes-message')
            
            print(f"Items v1: {len(items_v1)}")
            print(f"Items v2: {len(items_v2)}")
            
            primer_item = None
            items = items_v1 if items_v1 else items_v2
            
            if items:
                item = items[0]
                title = extraer_titulo(item)
                link_elem = item.find('a', href=True)
                
                primer_item = {
                    "titulo_extraido": title[:100] if title else "NO ENCONTRADO",
                    "tiene_link": bool(link_elem),
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
                "primer_item": primer_item
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
        
        response = requests.get(url, headers=HEADERS, timeout=10)
        
        soup = BeautifulSoup(response.text, 'html.parser')
        items = soup.find_all('li', class_='ui-search-layout__item')
        
        return {
            "url": url,
            "status": response.status_code,
            "items_encontrados": len(items),
            "html_length": len(response.text),
            "funciona": len(items) > 0,
            "html_es_valido": response.text.strip().startswith('<')
        }
    except Exception as e:
        return {
            "error": str(e)
        }

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
