"""
Portafolio 10 - Pedidos Serverless
Función AWS Lambda (Python) que atiende las rutas de la API HTTP:

  GET  /salud    -> comprueba que la API está funcionando
  GET  /pedidos  -> lista los pedidos guardados en DynamoDB
  POST /pedidos  -> valida y guarda un pedido nuevo en DynamoDB

Variable de entorno requerida:
  TABLE_NAME = Pedidos   (nombre de la tabla de DynamoDB)
"""
import json
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3

# Buena práctica: el nombre de la tabla NO se deja fijo en el código,
# se lee desde una variable de entorno.
TABLE_NAME = os.environ.get("TABLE_NAME", "Pedidos")

# Se crea FUERA del handler para reutilizar la conexión entre invocaciones
# (así las llamadas siguientes al "arranque en frío" son más rápidas).
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)

MAX_TEXTO = 50
MAX_CANTIDAD = 100


def _json_seguro(valor):
    """DynamoDB devuelve los números como Decimal; se convierten para poder usar json.dumps."""
    if isinstance(valor, Decimal):
        return int(valor) if valor == valor.to_integral_value() else float(valor)
    raise TypeError(f"Tipo no serializable: {type(valor)}")


def responder(codigo, cuerpo):
    """Construye la respuesta HTTP que espera API Gateway (integración proxy)."""
    return {
        "statusCode": codigo,
        "headers": {"Content-Type": "application/json; charset=utf-8"},
        "body": json.dumps(cuerpo, default=_json_seguro, ensure_ascii=False),
    }


def ahora_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def listar_pedidos():
    # Para esta demostración basta un scan limitado a 50 elementos.
    # En un sistema real se usaría una consulta (Query) con índice y paginación.
    resultado = table.scan(Limit=50)
    pedidos = sorted(
        resultado.get("Items", []),
        key=lambda pedido: pedido.get("fecha", ""),
        reverse=True,
    )
    return responder(200, {"total": len(pedidos), "pedidos": pedidos})


def crear_pedido(event):
    # 1) Leer el cuerpo de la petición (JSON)
    try:
        datos = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return responder(400, {"error": "El cuerpo debe ser un JSON válido"})

    if not isinstance(datos, dict):
        return responder(400, {"error": "El cuerpo debe ser un objeto JSON"})

    # 2) Validar los datos de entrada (nunca confiar en lo que envía el cliente)
    cliente = str(datos.get("cliente", "")).strip()
    producto = str(datos.get("producto", "")).strip()
    try:
        cantidad = int(datos.get("cantidad", 0))
    except (TypeError, ValueError):
        cantidad = 0

    errores = []
    if not 1 <= len(cliente) <= MAX_TEXTO:
        errores.append(f"cliente: debe tener entre 1 y {MAX_TEXTO} caracteres")
    if not 1 <= len(producto) <= MAX_TEXTO:
        errores.append(f"producto: debe tener entre 1 y {MAX_TEXTO} caracteres")
    if not 1 <= cantidad <= MAX_CANTIDAD:
        errores.append(f"cantidad: debe ser un número entero entre 1 y {MAX_CANTIDAD}")

    if errores:
        return responder(400, {"error": "Datos inválidos", "detalle": errores})

    # 3) Guardar en DynamoDB (la clave de partición es orderId)
    pedido = {
        "orderId": str(uuid.uuid4()),
        "cliente": cliente,
        "producto": producto,
        "cantidad": cantidad,
        "estado": "RECIBIDO",
        "fecha": ahora_iso(),
    }
    table.put_item(Item=pedido)
    return responder(201, {"mensaje": "Pedido creado correctamente", "pedido": pedido})


def lambda_handler(event, context):
    # routeKey tiene el formato "MÉTODO /ruta", por ejemplo "GET /pedidos"
    ruta = event.get("routeKey", "")
    parametros = event.get("queryStringParameters") or {}

    # Falla intencional (idea de Chaos Engineering): sirve para comprobar que
    # la alarma de CloudWatch y el aviso por correo funcionan de verdad.
    if ruta == "GET /salud" and parametros.get("simular_error") == "1":
        raise RuntimeError("Falla simulada para probar la alarma de CloudWatch")

    try:
        if ruta == "GET /salud":
            respuesta = responder(
                200, {"estado": "ok", "servicio": "p10-pedidos", "hora": ahora_iso()}
            )
        elif ruta == "GET /pedidos":
            respuesta = listar_pedidos()
        elif ruta == "POST /pedidos":
            respuesta = crear_pedido(event)
        else:
            respuesta = responder(404, {"error": "Ruta no encontrada"})
    except Exception as error:  # cualquier error inesperado -> 500 controlado
        print(f"ERROR en {ruta}: {error!r}")
        respuesta = responder(500, {"error": "Error interno del servidor"})

    # Este mensaje queda guardado en CloudWatch Logs (observabilidad)
    print(f"RUTA={ruta} ESTADO={respuesta['statusCode']}")
    return respuesta
