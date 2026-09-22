"""
Simulador de PLC — control de arranque/parada de un motor
============================================================

Modela el ciclo de scan determinístico de un PLC real:

    1. Lectura de entradas   (Entradas.leer)
    2. Ejecución del programa (Motor.ejecutar_logica)
    3. Actualización de salidas (PLC.actualizar_salidas)

Arquitectura (bajo acoplamiento entre piezas):
    - Motor:    estado, temperatura, velocidad y tiempo de trabajo del
                motor, con la lógica de transición de estados.
    - Entradas: botones y sensor de temperatura en un instante dado
                (lo que el PLC "congela" en la fase de lectura).
    - PLC:      orquesta el ciclo de scan (lee -> ejecuta -> actualiza).
"""

from dataclasses import dataclass
from enum import Enum


class Estado(str, Enum):
    DETENIDO = "DETENIDO"
    FUNCIONANDO = "FUNCIONANDO"
    PAUSADO = "PAUSADO"
    EMERGENCIA = "EMERGENCIA"


@dataclass
class Entradas:
    """Snapshot de botones y sensor, tal como los lee el PLC en cada ciclo."""
    arranque: bool = False
    parada: bool = False
    apagado: bool = False
    emergencia: bool = False
    reset: bool = False
    temperatura_sensor: float = 25.0  # °C


class Motor:
    """
    Estado interno del motor y lógica de transición.

    Parámetros configurables por motor (según su ficha técnica y el
    ambiente donde trabaja):
        umbral_falla_c:        temperatura a partir de la cual se
                                considera sobrecalentamiento.
        margen_recuperacion_c: cuántos grados tiene que bajar por
                                debajo del umbral para permitir el
                                reset tras una emergencia (histéresis).
        debounce_s:            segundos que la temperatura debe
                                mantenerse por encima del umbral,
                                mientras el motor está FUNCIONANDO,
                                antes de disparar EMERGENCIA. Filtra
                                picos falsos del sensor. No se aplica
                                al momento de arrancar: si el sensor ya
                                marca falla en ese instante, el
                                arranque se bloquea sin esperar.
        rampa_c_por_s:         cuántos puntos de velocidad (%) gana o
                                pierde por segundo al arrancar/parar
                                (simula la rampa de un variador).
    """

    def __init__(
        self,
        umbral_falla_c: float = 90.0,
        margen_recuperacion_c: float = 10.0,
        debounce_s: float = 2.0,
        rampa_pct_por_s: float = 25.0,
    ):
        self.estado = Estado.DETENIDO
        self.temperatura = 25.0
        self.velocidad = 0.0          # % de velocidad nominal
        self.tiempo_trabajo = 0.0     # segundos, se resetea al detenerse

        self.umbral_falla_c = umbral_falla_c
        self.margen_recuperacion_c = margen_recuperacion_c
        self.debounce_s = debounce_s
        self.rampa_pct_por_s = rampa_pct_por_s

        self._tiempo_sobre_umbral = 0.0  # acumulador para el debounce

    @property
    def en_falla_termica(self) -> bool:
        return self.temperatura >= self.umbral_falla_c

    @property
    def falla_resuelta(self) -> bool:
        return self.temperatura <= (self.umbral_falla_c - self.margen_recuperacion_c)

    def ejecutar_logica(self, entradas: Entradas, dt: float) -> None:
        """Fase 2 del ciclo de scan: evalúa la máquina de estados."""
        self.temperatura = entradas.temperatura_sensor

        # La emergencia por botón interrumpe cualquier estado, siempre.
        if entradas.emergencia and self.estado != Estado.EMERGENCIA:
            self._disparar_emergencia()

        elif self.estado == Estado.EMERGENCIA:
            if entradas.reset and self.falla_resuelta:
                self.estado = Estado.DETENIDO
                self._tiempo_sobre_umbral = 0.0
            # mientras no haya reset válido, se queda en EMERGENCIA

        elif self.estado == Estado.DETENIDO:
            if entradas.arranque and not self.en_falla_termica:
                # Si ya hay falla térmica al presionar arranque, se
                # bloquea directo: no tiene sentido esperar el
                # debounce cuando el sensor ya marca falla real.
                self.estado = Estado.FUNCIONANDO

        elif self.estado == Estado.FUNCIONANDO:
            if entradas.parada:
                self.estado = Estado.PAUSADO
            elif entradas.apagado:
                self.estado = Estado.DETENIDO
                self.tiempo_trabajo = 0.0
            else:
                self._chequear_sobrecalentamiento(dt)

        elif self.estado == Estado.PAUSADO:
            if entradas.arranque:
                self.estado = Estado.FUNCIONANDO
            elif entradas.apagado:
                self.estado = Estado.DETENIDO
                self.tiempo_trabajo = 0.0

        self._actualizar_velocidad_y_tiempo(dt)

    def _disparar_emergencia(self) -> None:
        self.estado = Estado.EMERGENCIA
        self._tiempo_sobre_umbral = 0.0

    def _chequear_sobrecalentamiento(self, dt: float) -> None:
        """Debounce: solo dispara EMERGENCIA tras `debounce_s` sostenidos."""
        if self.en_falla_termica:
            self._tiempo_sobre_umbral += dt
            if self._tiempo_sobre_umbral >= self.debounce_s:
                self._disparar_emergencia()
        else:
            self._tiempo_sobre_umbral = 0.0

    def _actualizar_velocidad_y_tiempo(self, dt: float) -> None:
        objetivo = 100.0 if self.estado == Estado.FUNCIONANDO else 0.0
        paso = self.rampa_pct_por_s * dt
        if self.velocidad < objetivo:
            self.velocidad = min(objetivo, self.velocidad + paso)
        elif self.velocidad > objetivo:
            self.velocidad = max(objetivo, self.velocidad - paso)

        if self.estado == Estado.FUNCIONANDO:
            self.tiempo_trabajo += dt


class PLC:
    """Orquesta el ciclo de scan: lectura -> ejecución -> actualización."""

    def __init__(self, motor: Motor):
        self.motor = motor
        self.salidas = {}

    def ciclo_de_scan(self, entradas: Entradas, dt: float) -> dict:
        # 1) Lectura de entradas: ya llega "congelada" como parámetro.
        # 2) Ejecución del programa:
        self.motor.ejecutar_logica(entradas, dt)
        # 3) Actualización de salidas:
        self.salidas = self._actualizar_salidas()
        return self.salidas

    def _actualizar_salidas(self) -> dict:
        m = self.motor
        luces = {
            Estado.DETENIDO: None,
            Estado.FUNCIONANDO: "verde",
            Estado.PAUSADO: "amarilla",
            Estado.EMERGENCIA: "roja",
        }[m.estado]

        return {
            "contactor_motor": m.estado == Estado.FUNCIONANDO,
            "luz": luces,
            "pantalla": {
                "estado": m.estado.value,
                "temperatura_c": round(m.temperatura, 1),
                "velocidad_pct": round(m.velocidad, 1),
                "tiempo_trabajo_s": round(m.tiempo_trabajo, 1),
            },
        }


if __name__ == "__main__":
    # Demo simple: simula unos ciclos de scan a mano para mostrar el
    # comportamiento (arranque, rampa, sobrecalentamiento, emergencia).
    motor = Motor(umbral_falla_c=90.0, margen_recuperacion_c=10.0, debounce_s=2.0)
    plc = PLC(motor)

    escenario = [
        Entradas(arranque=True, temperatura_sensor=25.0),
        Entradas(temperatura_sensor=40.0),
        Entradas(temperatura_sensor=95.0),   # empieza a sobrecalentarse
        Entradas(temperatura_sensor=96.0),   # sigue en falla (debounce corriendo)
        Entradas(temperatura_sensor=97.0),   # supera 2s en falla -> EMERGENCIA
        Entradas(temperatura_sensor=70.0),   # se enfría, pero no resuelto aún
        Entradas(temperatura_sensor=79.0, reset=True),  # < 90-10=80 -> reset ok
    ]

    dt = 1.0  # 1 segundo por ciclo, solo para el demo
    for i, entradas in enumerate(escenario, start=1):
        salidas = plc.ciclo_de_scan(entradas, dt)
        print(f"ciclo {i}: {salidas}")
