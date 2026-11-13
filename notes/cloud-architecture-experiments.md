# CloudLab RFC — dos arquitecturas visuales para cúmulos (sin cambiar la física)

> **Para Claude y quienes revisen XP-Gliding.** Propuesta experimental. No reemplaza `cumulus.*`, no cambia `engine/clouds.py` ni `adapter/clouds.py` en esta PR. **No ha sido validada visualmente en X-Plane.**

## Diagnóstico: por qué las iteraciones convergen al mismo aspecto

En `tools/make_cloud_objs.py` hay un único `LAYERS` de ocho capas (tres torres, top, low, edge, wisp y base), un atlas de 16 celdas y un único objeto `cumulus.obj`. `adapter/clouds.py` modifica la escala y el rumbo de ese mismo objeto; ese rumbo no cambia la familia de siluetas de los billboards. Cambiar luz, alpha, ruido y límites de las cajas produce retoques sobre una **misma topología**, no arquitecturas realmente distintas. La v12 fue elegida tras pruebas; no se propone revertirla.

Por favor, antes de seguir ajustando números del generador actual, comprobar experimentalmente dos hipótesis con salidas totalmente aisladas en `tools/cloudlab/`.

## Prototipo A: un cúmulo casi completo por sprite

Una celda del atlas representa la **silueta integral de un pequeño cúmulo**: base, cuerpo y zonas de sombra ya compuestas en una sola imagen RGBA. Pocos billboards anchos forman el perfil; un grupo menor de fragmentos aporta algo de profundidad. No se construye la silueta ensamblando cientos de lóbulos gaussianos en pantalla.

**Resultado que buscamos:** menos efecto de «bolas de algodón» a 2–5 km; aspecto legible también durante la formación y disipación, con pocos sprites.

**Riesgos:** efecto de cartón al rodear la nube; varias nubes idénticas; sombreado pintado que no coincide con el sol; transparencias y bordes visibles al acercarse. No presentarlo como una nube volumétrica. Evitar `INITIAL_ROTATION` aleatorio en las siluetas completas porque inclina la base.

**Medición separada:** probar la silueta grande sola y después añadir fragmentos, sin reajustar luz y forma al mismo tiempo.

## Prototipo B: fragmentos fotográficos con disposición tridimensional

Cada celda representa un **recorte irregular de densidad nubosa** con granulado y sombra internos, en lugar de pequeños discos/bulbos generados matemáticamente. Se distribuyen sprites en varios cuerpos tridimensionales asimétricos: núcleo, crecimiento desplazado, ala baja, volumen posterior y base suave; **no** tres torres calcadas.

**Resultado que buscamos:** perspectiva y parallax mejores que A, sin volver a una cadena de círculos. La variedad principal procede de la estructura de distribución y del arte dentro de cada celda, no de variar `LIGHT` o `ALPHA_CURVE`.

**Riesgos:** acumulación excesiva de transparencias (*overdraw*), costuras entre recortes, base blanca o en forma de plato, falta de orden de profundidad entre emisores y repetición de un mismo perfil. Es posible que visualmente rinda peor que la v12: medirlo.

## Interfaz de pruebas compatible con el proyecto actual

Ambos prototipos se han generado **localmente**, fuera de esta rama, como paquetes separados `cu84` (A) y `cu85` (B), cada uno con `cuN.png`, `cuN.pss` y `cuN_plugin.obj`. La generación y una validación sintáctica de estructuras han terminado, pero **no hay capturas en X-Plane**. Los seis archivos están disponibles para transferir al equipo de pruebas junto con un generador y una guía; **no se incluyen en esta PR de propuesta**, para evitar introducir binarios o activos de producción sin una evaluación previa.

Contrato que deben cumplir:

- Atlas RGBA 1024×1024, 4×4 celdas, exactamente como el formato actual.
- Emisores con `xp_gliding/clouds/rate` y `xp_gliding/clouds/scale` en el orden que usa CloudLab con `kind=11`.
- Hasta tres `SUB_EMITTER` por `EMITTER`: el proyecto documenta un crash observado con ocho (`notes/cloud-looks.md`). **No asumir** que otras cantidades son seguras sin probar.
- Nunca modificar `xp_gliding/assets/clouds/cumulus.png`, `cumulus.pss` ni `cumulus.obj` durante este ensayo.
- Mantener la altura de nube compatible con la base calculada por `CloudHeights`; comprobar visualmente el fondo del sprite y el offset del emisor.
- No tocar `CloudPlanner`, el arrastre por viento, la lógica de sombreado ni los pools de anillos para cambiar la apariencia.

CloudLab ya permite mantener versiones diferentes cargadas. Si sus recursos se han copiado a `Resources/plugins/PythonPlugins/xpg_cloudlab/`, las operaciones son:

```bash
python tools/cloudlab/fly_cloud.py do load=84
python tools/cloudlab/fly_cloud.py do ver=84 kind=11 count=1 dist_m=3500 dy_m=350 scale=1 value=20 place=1
# Tras breve llenado, volver a la tasa estable para que no se acumulen partículas:
python tools/cloudlab/fly_cloud.py do value=1 set_value=1 --view forward --shot

python tools/cloudlab/fly_cloud.py do load=85
python tools/cloudlab/fly_cloud.py do ver=85 kind=11 count=1 dist_m=3500 dy_m=350 scale=1 value=20 place=1
python tools/cloudlab/fly_cloud.py do value=1 set_value=1 --view forward --shot
```

Importante: `kind=11` presupone XP-Gliding activo para registrar los dos datarefs; `load` es asíncrono, por lo que hay que comprobar `xpg_cloudlab/loaded` antes de `place`. Usar `clear=1` cuando se quiera borrar una escena anterior. No mantener `value=20` durante minutos.

## Matriz A/B con la v12 como control

| Escena | Hipótesis a evaluar | Evidencia |
| --- | --- | --- |
| Una nube a 3,5 km, observador bajo la base | Silueta natural, gris interior, sin disco | Capturas lado a lado, mismo clima y cámara |
| A 0,5–1 km, rodear ~180° | ¿Se nota plano? ¿Hay parallax real? | Vídeo/capturas en varios ángulos |
| Nube joven y nube agotándose | ¿Se ve cúmulo o «popcorn»? | Capturas con tasa y edad controladas |
| 3–5 km, con dos nubes superpuestas | Orden de transparencias, contornos | Capturas y prueba de anillos |
| Rejilla de ~200 nubes | Pérdida de FPS, GPU, CPU, sobreimpresión | Repetir protocolo de `notes/cloud-looks.md` |
| Aproximación nocturna y con viento | Coherencia de iluminación, movimiento, cortes | Capturas y registros de log |

Comparar también la **v12 actual** con las mismas condiciones; registrar versiones, hora, X-Plane, Vulkan, posición, configuración gráfica y número de partículas.

## Qué le pido a Claude

1. **No** seguir optimizando v12 a ciegas. Montar primero las dos variantes sin cambiar el núcleo de térmicas.
2. Verificar carga en X-Plane, `Log.txt`, aspecto desde abajo y de lado, base, bordes, repetición y coste. Una hipótesis estructural a la vez.
3. Informar cuál gana en (i) silueta, (ii) volumen al rodear, (iii) maduración, (iv) coste, incluso si gana la v12.
4. Si ninguna funciona, explorar un tercer acercamiento verdaderamente distinto: **impostores multivista preparados fuera de línea** o una geometría 3D simple con ruido y textura RGBA. Antes, confirmar las restricciones de OBJ8/Vulkan y el coste. No afirmar que el SDK expone nubes volumétricas nativas.
5. Solo después de una selección visual: diseñar un catálogo de 3–5 familias de nube, elegido por semilla determinista de cada térmica, sin alterar el lugar o ciclo de vida del ascenso. El cambio de instancia requiere estudiar la carga, los pools de anillos y el orden de partículas documentado en `docs/findings/particle-emitters.md`.

**Criterio de aceptación de esta PR:** documentar alternativas y protocolo; **no** prometer mejoras visuales ni fusionar activos no validados.
