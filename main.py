from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Optional
import requests
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime
import os

app = FastAPI(title="MercadoLibre Scanner API", version="1.0.0")

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
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'es-CL,es;q=0.9',
}

# ALMACENAMIENTO EN MEMORIA (Railway no persiste archivos)
# Los datos se mantienen mientras el servidor está activo
PRODUCTOS_DB = {}  # {id: producto}

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
    productos_nuevos: int
    celulares: Dict[str, int]
    notebooks: Dict[str, int]
    nuevos: List[Producto]
    timestamp: str

class ProductosResponse(BaseModel):
    success: bool
    total: int
    celulares: List[Producto]
    notebooks: List[Producto]

class IDsResponse(BaseModel):
    success: bool
    total: int
    celulares_ids: List[str]
    notebooks_ids: List[str]

class CompareRequest(BaseModel):
    celulares_ids: List[str]
    notebooks_ids: List[str]

class CompareResponse(BaseModel):
    success: bool
    nuevos_encontrados: int
    celulares_nuevos: List[Producto]
    notebooks_nuevos: List[Producto]

# Funciones auxiliares
def extraer_titulo(item):
    """Extrae el título - IGUAL QUE EL CÓDIGO LOCAL"""
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
    """Verifica si una página existe - IGUAL QUE LOCAL"""
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code != 200:
            return False, 0
        
        soup = BeautifulSoup(response.text, 'html.parser')
        items = soup.find_all('li', class_='ui-search-layout__item')
        if not items:
            items = soup.find_all('div', class_='ui-search-result')
        
        return len(items) > 0, len(items)
    except Exception as e:
        print(f"Error verificando página: {e}")
        return False, 0

def escanear_mercadolibre():
    """Escanea MercadoLibre - LÓGICA EXACTA DEL CÓDIGO LOCAL"""
    global PRODUCTOS_DB
    
    productos_json_previos = PRODUCTOS_DB.copy()
    todos_productos_escaneados = {}
    productos_nuevos = []
    
    stats = {
        "celulares": {"total": 0, "nuevos": 0},
        "notebooks": {"total": 0, "nuevos": 0}
    }
    
    print(f"\n{'='*60}")
    print(f"🔍 INICIANDO ESCANEO")
    print(f"📦 Productos en memoria: {len(productos_json_previos)}")
    print(f"{'='*60}\n")
    
    for categoria, url_base in URLS.items():
        print(f"\n{'='*60}")
        print(f"Escaneando: {categoria.upper()}")
        print(f"{'='*60}")
        
        total_escaneados_categoria = 0
        productos_nuevos_categoria = 0
        
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
                print(f"   ⚠️ Página {pagina} no existe o no tiene productos")
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
                
                total_escaneados_categoria += len(items)
                
                for item in items:
                    try:
                        # Extraer título
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
                            
                            # Guardar SIEMPRE
                            todos_productos_escaneados[product_id] = producto
                            stats[categoria]["total"] += 1
                            
                            # Comparar con previos
                            es_nuevo = product_id not in productos_json_previos
                            if es_nuevo:
                                productos_nuevos.append(producto)
                                stats[categoria]["nuevos"] += 1
                                productos_nuevos_categoria += 1
                                print(f"   🆕 NUEVO [{product_id}]: {title[:50]}")
                            else:
                                print(f"   ✅ Ya existe [{product_id}]: {title[:40]}")
                        else:
                            if not title:
                                print(f"   ⚠️ Producto sin título - ID:{bool(product_id)} Link:{bool(link)}")
                    
                    except Exception as e:
                        print(f"   ❌ Error procesando item: {e}")
                        continue
            
            except Exception as e:
                print(f"   ❌ Error en página {pagina}: {e}")
            
            pagina += 1
        
        print(f"\n✅ {categoria}: {total_escaneados_categoria} productos escaneados, {productos_nuevos_categoria} NUEVOS en {pagina-1} página(s)")
    
    # Actualizar base de datos en memoria
    PRODUCTOS_DB = todos_productos_escaneados.copy()
    
    print(f"\n{'='*60}")
    print(f"🎉 ESCANEO COMPLETADO")
    print(f"   Total escaneado: {len(todos_productos_escaneados)}")
    print(f"   Nuevos encontrados: {len(productos_nuevos)}")
    print(f"   En memoria ahora: {len(PRODUCTOS_DB)}")
    print(f"{'='*60}\n")
    
    return todos_productos_escaneados, productos_nuevos, stats

# ENDPOINTS

@app.get("/")
def root():
    return {
        "app": "MercadoLibre Scanner API",
        "version": "1.0.0",
        "storage": "In-Memory (RAM)",
        "note": "Los datos se mantienen mientras el servidor está activo",
        "endpoints": {
            "GET /health": "Health check",
            "POST /scan": "Escanear MercadoLibre y actualizar base de datos",
            "GET /productos": "Obtener todos los productos guardados",
            "GET /productos/ids": "Obtener solo los IDs",
            "POST /compare": "Comparar IDs del cliente",
            "GET /stats": "Estadísticas",
            "GET /debug/memory": "Ver estado de la memoria"
        }
    }

@app.get("/health")
def health():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "productos_en_memoria": len(PRODUCTOS_DB)
    }

@app.post("/scan", response_model=ScanResponse)
def scan_mercadolibre():
    """Escanea MercadoLibre - EXACTO AL CÓDIGO LOCAL"""
    try:
        todos_productos, productos_nuevos, stats = escanear_mercadolibre()
        
        return ScanResponse(
            success=True,
            message="Escaneo completado exitosamente",
            total_productos=len(todos_productos),
            productos_nuevos=len(productos_nuevos),
            celulares={
                "total": stats["celulares"]["total"],
                "nuevos": stats["celulares"]["nuevos"]
            },
            notebooks={
                "total": stats["notebooks"]["total"],
                "nuevos": stats["notebooks"]["nuevos"]
            },
            nuevos=[Producto(**p) for p in productos_nuevos],
            timestamp=datetime.now().isoformat()
        )
    
    except Exception as e:
        import traceback
        print(f"\n❌ ERROR EN SCAN:")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error en escaneo: {str(e)}")

@app.get("/productos", response_model=ProductosResponse)
def get_productos():
    """Retorna todos los productos"""
    celulares = [p for p in PRODUCTOS_DB.values() if p['categoria'] == 'celulares']
    notebooks = [p for p in PRODUCTOS_DB.values() if p['categoria'] == 'notebooks']
    
    return ProductosResponse(
        success=True,
        total=len(PRODUCTOS_DB),
        celulares=[Producto(**p) for p in celulares],
        notebooks=[Producto(**p) for p in notebooks]
    )

@app.get("/productos/ids", response_model=IDsResponse)
def get_productos_ids():
    """Retorna solo IDs"""
    celulares_ids = [p['id'] for p in PRODUCTOS_DB.values() if p['categoria'] == 'celulares']
    notebooks_ids = [p['id'] for p in PRODUCTOS_DB.values() if p['categoria'] == 'notebooks']
    
    return IDsResponse(
        success=True,
        total=len(PRODUCTOS_DB),
        celulares_ids=celulares_ids,
        notebooks_ids=notebooks_ids
    )

@app.post("/compare", response_model=CompareResponse)
def compare_productos(request: CompareRequest):
    """Compara IDs"""
    cliente_ids = set(request.celulares_ids + request.notebooks_ids)
    
    productos_nuevos = {
        prod_id: prod for prod_id, prod in PRODUCTOS_DB.items()
        if prod_id not in cliente_ids
    }
    
    celulares_nuevos = [p for p in productos_nuevos.values() if p['categoria'] == 'celulares']
    notebooks_nuevos = [p for p in productos_nuevos.values() if p['categoria'] == 'notebooks']
    
    return CompareResponse(
        success=True,
        nuevos_encontrados=len(productos_nuevos),
        celulares_nuevos=[Producto(**p) for p in celulares_nuevos],
        notebooks_nuevos=[Producto(**p) for p in notebooks_nuevos]
    )

@app.get("/stats")
def get_stats():
    """Estadísticas"""
    celulares = [p for p in PRODUCTOS_DB.values() if p['categoria'] == 'celulares']
    notebooks = [p for p in PRODUCTOS_DB.values() if p['categoria'] == 'notebooks']
    
    ultima_actualizacion = "Nunca"
    if PRODUCTOS_DB:
        timestamps = [p.get('timestamp', '00:00:00') for p in PRODUCTOS_DB.values()]
        ultima_actualizacion = max(timestamps)
    
    return {
        "success": True,
        "total_productos": len(PRODUCTOS_DB),
        "celulares": len(celulares),
        "notebooks": len(notebooks),
        "ultima_actualizacion": ultima_actualizacion,
        "storage": "In-Memory (RAM)"
    }

@app.get("/debug/memory")
def debug_memory():
    """Ver estado de la memoria"""
    return {
        "productos_en_memoria": len(PRODUCTOS_DB),
        "primeros_5_ids": list(PRODUCTOS_DB.keys())[:5],
        "celulares": len([p for p in PRODUCTOS_DB.values() if p['categoria'] == 'celulares']),
        "notebooks": len([p for p in PRODUCTOS_DB.values() if p['categoria'] == 'notebooks'])
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
