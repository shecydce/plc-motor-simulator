# Simulador de PLC — Control de arranque/parada de motor

Simulador en Python que modela el **ciclo de scan determinístico** de un PLC real, aplicado a un caso de uso industrial concreto: el control de arranque/parada de un motor con protección térmica.

## Por qué este proyecto

La automatización industrial con PLC se programa distinto a un script común: en vez de ejecutarse una sola vez, un PLC repite sin parar un ciclo de tres fases (lectura de entradas → ejecución del programa → actualización de salidas), muchas veces por segundo. Este simulador reproduce ese comportamiento en Python, incluyendo una máquina de estados completa y una protección térmica con histéresis y filtro anti-rebote, tal como se diseñaría en un PLC real.

## Qué hace

- Controla un motor con cuatro estados: `DETENIDO`, `FUNCIONANDO`, `PAUSADO` y `EMERGENCIA`.
- Cinco entradas: arranque, parada (pausa retomable), apagado (corte definitivo), emergencia y sensor de temperatura.
- Protección por sobrecalentamiento:
  - Umbral de falla y margen de recuperación (histéresis) **configurables por motor**, ya que distintos motores toleran distintas temperaturas y se enfrían a distinto ritmo según el ambiente.
  - Filtro anti-rebote (*debounce*) de 2 segundos mientras el motor está funcionando, para no disparar una emergencia por un pico de lectura falso.
  - Si el sensor **ya** marca falla en el instante de presionar arranque, el arranque se bloquea directo — no tiene sentido esperar el debounce cuando la falla ya es real.
  - El reset tras una emergencia solo se habilita cuando la temperatura bajó del umbral de recuperación (no alcanza con tocar el botón).
- Velocidad simulada con rampa de aceleración/desaceleración, como la de un variador de frecuencia real.
- Salidas: contactor del motor, luces (verde/amarilla/roja) y datos de pantalla (temperatura, velocidad, tiempo de trabajo).

## Arquitectura

Tres clases con responsabilidades separadas (bajo acoplamiento):

| Clase | Responsabilidad |
|---|---|
| `Motor` | Estado actual, temperatura, velocidad, tiempo de trabajo y la lógica de transición entre estados. |
| `Entradas` | Snapshot de botones y sensor en un instante dado — lo que el PLC "congela" en la fase de lectura. |
| `PLC` | Orquesta el ciclo de scan: lee entradas, le pasa el control al `Motor`, y actualiza las salidas. |

```
Entradas  --(lectura)-->  PLC.ciclo_de_scan()  --(ejecución)-->  Motor
                                   |
                                   v
                          (actualización de salidas)
                        contactor · luces · pantalla
```

## Uso

```bash
python3 plc_motor_simulator.py
```

Corre un escenario de demostración con arranque, rampa de velocidad, un evento de sobrecalentamiento sostenido y el reset posterior, imprimiendo el estado de las salidas en cada ciclo de scan.

## Tecnologías

Python 3 (sin dependencias externas) — `dataclasses` y `enum` de la librería estándar.

## Posibles mejoras

- Interfaz gráfica simple para visualizar estados y pantalla en tiempo real.
- Persistencia de logs de eventos (fallas, arranques, tiempos de uso).
- Soporte para simular múltiples motores en paralelo.
