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
from pathlib import Path

app = FastAPI(title="MercadoLibre Scanner API", version="1.0.0")

# CORS para permitir peticiones desde Flutter
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

# Directorio para JSON
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

JSON_FILES = {
    "celulares": DATA_DIR / "celulares.json",
    "notebooks": DATA_DIR / "notebooks.json"
}

# Modelos Pydantic
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
def cargar_productos_json():
    """Carga productos desde JSON"""
    productos = {}
    
    for categoria, archivo in JSON_FILES.items():
        if archivo.exists():
            try:
                with open(archivo, 'r', encoding='utf-8') as f:
                    productos_lista = json.load(f)
                    for prod in productos_lista:
                        productos[prod['id']] = prod
            except Exception as e:
                print(f"Error cargando {archivo}: {e}")
    
    return productos

def guardar_productos_json(todos_productos: Dict):
    """Guarda productos en JSON por categoría"""
    productos_por_categoria = {
        "celulares": [],
        "notebooks": []
    }
    
    for prod in todos_productos.values():
        categoria = prod.get('categoria')
        if categoria in productos_por_categoria:
            productos_por_categoria[categoria].append(prod)
    
    for categoria, productos in productos_por_categoria.items():
        archivo = JSON_FILES[categoria]
        try:
            productos_ordenados = sorted(
                productos,
                key=lambda x: x.get('timestamp', '00:00:00'),
                reverse=True
            )
            
            with open(archivo, 'w', encoding='utf-8') as f:
                json.dump(productos_ordenados, f, ensure_ascii=False, indent=2)
                
            print(f"✅ {categoria}: {len(productos)} productos guardados")
        except Exception as e:
            print(f"❌ Error guardando {archivo}: {e}")

def extraer_titulo(item):
    """Extrae el título de un item de múltiples formas"""
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
    """Escanea MercadoLibre y retorna productos"""
    productos_json_previos = cargar_productos_json()
    todos_productos_escaneados = {}
    productos_nuevos = []
    
    stats = {
        "celulares": {"total": 0, "nuevos": 0},
        "notebooks": {"total": 0, "nuevos": 0}
    }
    
    print(f"\n{'='*60}")
    print(f"🔍 INICIANDO ESCANEO")
    print(f"📦 Productos en JSON previo: {len(productos_json_previos)}")
    print(f"{'='*60}\n")
    
    for categoria, url_base in URLS.items():
        print(f"\n{'='*60}")
        print(f"Escaneando: {categoria.upper()}")
        print(f"{'='*60}")
        
        num_paginas_max = PAGINAS_CONFIG.get(categoria, 1)
        pagina = 1
        
        while pagina <= num_paginas_max:
            if pagina == 1:
                url = url_base
            else:
                offset = (pagina - 1) * 50 + 1
                url = url_base.replace('_OrderId', f'_Desde_{offset}_OrderId')
            
            print(f"📄 Página {pagina}...")
            
            existe, num_items = verificar_pagina_existe(url)
            if not existe:
                print(f"   ⚠️ Página {pagina} no existe")
                break
            
            print(f"   ✅ {num_items} items encontrados")
            
            try:
                response = requests.get(url, headers=HEADERS, timeout=15)
                if response.status_code != 200:
                    pagina += 1
                    continue
                
                soup = BeautifulSoup(response.text, 'html.parser')
                items = soup.find_all('li', class_='ui-search-layout__item')
                if not items:
                    items = soup.find_all('div', class_='ui-search-result')
                
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
                            
                            todos_productos_escaneados[product_id] = producto
                            stats[categoria]["total"] += 1
                            
                            # Comparar con JSON previo
                            es_nuevo = product_id not in productos_json_previos
                            if es_nuevo:
                                productos_nuevos.append(producto)
                                stats[categoria]["nuevos"] += 1
                                print(f"   🆕 NUEVO: {product_id}")
                    
                    except Exception as e:
                        print(f"   ❌ Error procesando item: {e}")
                        continue
            
            except Exception as e:
                print(f"   ❌ Error en página {pagina}: {e}")
            
            pagina += 1
        
        print(f"✅ {categoria}: {stats[categoria]['total']} productos, {stats[categoria]['nuevos']} nuevos")
    
    # Guardar productos
    print(f"\n💾 Guardando {len(todos_productos_escaneados)} productos...")
    guardar_productos_json(todos_productos_escaneados)
    
    print(f"\n{'='*60}")
    print(f"🎉 ESCANEO COMPLETADO")
    print(f"   Total: {len(todos_productos_escaneados)}")
    print(f"   Nuevos: {len(productos_nuevos)}")
    print(f"{'='*60}\n")
    
    return todos_productos_escaneados, productos_nuevos, stats

# ENDPOINTS

@app.get("/")
def root():
    """Endpoint raíz"""
    return {
        "app": "MercadoLibre Scanner API",
        "version": "1.0.0",
        "endpoints": {
            "GET /health": "Health check",
            "POST /scan": "Escanear MercadoLibre y actualizar base de datos",
            "GET /productos": "Obtener todos los productos guardados",
            "GET /productos/ids": "Obtener solo los IDs de productos",
            "POST /compare": "Comparar IDs del cliente con la base de datos",
            "GET /stats": "Estadísticas generales"
        }
    }

@app.get("/health")
def health():
    """Health check para Railway"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat()
    }

@app.post("/scan", response_model=ScanResponse)
def scan_mercadolibre(background_tasks: BackgroundTasks):
    """
    Escanea MercadoLibre, compara con JSON guardado, 
    guarda nuevos productos y retorna resultado
    """
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
        raise HTTPException(status_code=500, detail=f"Error en escaneo: {str(e)}")

@app.get("/productos", response_model=ProductosResponse)
def get_productos():
    """Retorna todos los productos guardados"""
    try:
        productos = cargar_productos_json()
        
        celulares = [p for p in productos.values() if p['categoria'] == 'celulares']
        notebooks = [p for p in productos.values() if p['categoria'] == 'notebooks']
        
        return ProductosResponse(
            success=True,
            total=len(productos),
            celulares=[Producto(**p) for p in celulares],
            notebooks=[Producto(**p) for p in notebooks]
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo productos: {str(e)}")

@app.get("/productos/ids", response_model=IDsResponse)
def get_productos_ids():
    """
    Retorna solo los IDs de productos guardados
    (Ligero para comparación desde Flutter)
    """
    try:
        productos = cargar_productos_json()
        
        celulares_ids = [p['id'] for p in productos.values() if p['categoria'] == 'celulares']
        notebooks_ids = [p['id'] for p in productos.values() if p['categoria'] == 'notebooks']
        
        return IDsResponse(
            success=True,
            total=len(productos),
            celulares_ids=celulares_ids,
            notebooks_ids=notebooks_ids
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo IDs: {str(e)}")

@app.post("/compare", response_model=CompareResponse)
def compare_productos(request: CompareRequest):
    """
    Compara IDs enviados desde Flutter con los del servidor
    Retorna solo los productos nuevos (que el cliente no tiene)
    """
    try:
        productos = cargar_productos_json()
        
        # IDs que tiene el cliente
        cliente_ids = set(request.celulares_ids + request.notebooks_ids)
        
        # Productos nuevos (que el cliente no tiene)
        productos_nuevos = {
            prod_id: prod for prod_id, prod in productos.items()
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
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error comparando: {str(e)}")

@app.get("/stats")
def get_stats():
    """Estadísticas generales"""
    try:
        productos = cargar_productos_json()
        
        celulares = [p for p in productos.values() if p['categoria'] == 'celulares']
        notebooks = [p for p in productos.values() if p['categoria'] == 'notebooks']
        
        # Última actualización
        ultima_actualizacion = "Nunca"
        if productos:
            timestamps = [p.get('timestamp', '00:00:00') for p in productos.values()]
            ultima_actualizacion = max(timestamps)
        
        return {
            "success": True,
            "total_productos": len(productos),
            "celulares": len(celulares),
            "notebooks": len(notebooks),
            "ultima_actualizacion": ultima_actualizacion,
            "archivos": {
                "celulares_json": str(JSON_FILES["celulares"].exists()),
                "notebooks_json": str(JSON_FILES["notebooks"].exists())
            }
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo stats: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)