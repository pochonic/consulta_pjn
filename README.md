# PJN SCW

Desarrollo separado para consultar el Sistema de Consultas Web del Poder Judicial de la Nación.

Flujo de la primera versión:

1. Login en el portal PJN.
2. Abrir `Consultas` desde el menú izquierdo.
3. Ordenar por `FECHA`.
4. Extraer las primeras cinco filas.

Cada resultado devuelve exactamente:

- `Expediente`
- `Dependencia`
- `Carátula`
- `Situación`
- `Últ. Act.`

La columna de favoritos y el detalle individual no se procesan.

## Instalación

```powershell
cd outputs\pjn-scw-cli
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
playwright install chromium
```

El cliente está en `src/pjn_scw/client.py`. La UI/API de PJN se agregará en este proyecto, sin reutilizar la configuración ni la base SQLite de MEV.

## Railway + Telegram

La ejecución programada se ejecuta con:

```powershell
python -m pjn_scw.cron
```

Configura las variables de `.env.example` en Railway. `TELEGRAM_ALLOWED_CHAT_IDS` indica los chats que reciben el resultado.

En Railway configura el servicio como Cron Job con:

```cron
*/30 12-18 * * *
```

Railway usa UTC: esto cubre las 09:00 a 15:30 de Argentina. El script descarta la ejecución de las 15:30 y consulta sólo a las 09:00, 09:30, ..., 14:30 y 15:00.

Para consultas manuales por Telegram, el modo alternativo es ejecutar `python -m pjn_scw.bot` como servicio persistente; no debe ejecutarse junto con el cron si ambos usan el mismo bot.

En Railway, crea un Volume montado en `/app/data` para conservar `pjn.sqlite3`. El cron puede terminar después de enviar el mensaje; el volumen mantiene el histórico entre ejecuciones.
