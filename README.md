
---

```markdown
# FinBase - The Open Ledger


<!-- Reemplaza la URL de arriba con la URL definitiva de tu logo cuando la tengas -->

**Misión: Construir la primera base de datos global de activos financieros, abierta, colaborativa y gratuita, para democratizar el acceso a información de calidad.**

[![Estado del Proyecto](https://img.shields.io/badge/estado-en%20desarrollo-green.svg)](https://github.com/AmericoGarciaG/FinBase)
[![Licencia](https://img.shields.io/badge/licencia-MIT-blue.svg)](./LICENSE)
[![GitHub Issues](https://img.shields.io/github/issues/AmericoGarciaG/FinBase.svg)](https://github.com/AmericoGarciaG/FinBase)
<!-- Reemplaza 'tu_usuario/finbase' con tu repositorio real -->

---

## Manifiesto: La Base de Datos Financiera Abierta

Creemos que el conocimiento financiero no debería estar restringido a unos cuantos. La información es poder, y el acceso a ella define quién puede innovar, investigar y transformar el futuro de las finanzas.

Hoy, las fuentes abiertas que existen —como Yahoo Finance y otras bases gratuitas— son limitadas, incompletas y poco confiables. Y las fuentes premium, aunque poderosas, están reservadas para quienes pueden pagar precios prohibitivos. Esto genera una brecha injusta entre quienes tienen acceso a datos de calidad y quienes no.

**Nosotros queremos cambiar eso.**

### Nuestra Visión

Construir la primera base de datos global de activos financieros abierta y colaborativa, diseñada para ser gratuita, escalable y de acceso universal. Un espacio vivo y transparente que con el tiempo se convierta en la referencia confiable de información financiera, accesible para investigadores, desarrolladores, traders independientes, estudiantes y curiosos de todo el mundo.

### Nuestro Compromiso

-   **Acceso libre y abierto:** datos financieros disponibles para todos, sin barreras de pago ni muros cerrados.
-   **Calidad y transparencia:** estándares elevados de validación y trazabilidad de datos.
-   **Colaboración comunitaria:** un proyecto construido por la comunidad, para la comunidad.
-   **Escalabilidad orgánica:** una arquitectura tecnológica sólida que crecerá junto con la demanda.
-   **Evolución constante:** de usar datos de terceros a convertirnos en una fuente primaria, directa y confiable.

---

## 🏗️ Arquitectura del Sistema

FinBase está construido sobre una arquitectura de microservicios desacoplados que se comunican a través de un bus de mensajes (RabbitMQ). Este diseño garantiza que cada componente sea independiente, reemplazable y escalable.

```
[Fuentes de Datos] -> [Collectors] -> [Cola de Datos Crudos] -> [Servicio de Calidad] -> [Cola de Datos Limpios] -> [Servicio de Almacenamiento] -> [Base de Datos] -> [API] -> [Usuarios]
```

El proyecto en sí mismo es un laboratorio para descubrir la manera más eficiente, óptima y vanguardista de guardar, controlar, acceder y extraer información financiera con el mínimo de recursos.

## 📦 Microservicios

Este repositorio contiene todos los microservicios que componen el ecosistema de FinBase. Cada servicio reside en su propia carpeta dentro del directorio `/services`.

| Servicio                                                     | Lenguaje | Descripción                                      | Estado            |
| :----------------------------------------------------------- | :------- | :----------------------------------------------- | :---------------- |
| [`services/collector-yfinance`](./services/collector-yfinance) | Python   | Colector de datos para Yahoo Finance.            | ✅ **Activo**     |
| `services/quality-service`                                   | Python   | Validador y limpiador de datos.                  | 🚧 En desarrollo  |
| `services/storage-service`                                   | Python   | Servicio de almacenamiento en TimescaleDB.       | 📝 Planificado    |
| `services/api-service`                                       | Python   | API REST/WebSocket para acceso a los datos.      | 📝 Planificado    |

## ⚡ Guía de Inicio Rápido

### Prerrequisitos

-   [Git](https://git-scm.com/)
-   [Docker](https://www.docker.com/) y [Docker Compose](https://docs.docker.com/compose/)

### 1. Clonar el Repositorio

```bash
git clone https://github.com/AmericoGarciaG/FinBase.git
cd finbase
```

### 2. Ejecutar un Servicio Individualmente

Cada microservicio puede ser ejecutado de forma independiente para desarrollo y pruebas. Por ejemplo, para levantar el colector de Yahoo Finance:

```bash
# Navegar a la carpeta del servicio
cd services/collector-yfinance

# Crear tu archivo .env a partir del ejemplo
cp .env.example .env

# (Opcional) Edita el archivo .env para cambiar los tickers o el intervalo

# Levantar el servicio y su dependencia (RabbitMQ)
docker compose up --build
```
Para más detalles, consulta el `README.md` dentro de la carpeta de cada servicio.

*(Próximamente se añadirá un `docker-compose.yml` en la raíz para orquestar todo el sistema con un solo comando).*

## 🤝 Cómo Contribuir

¡Este proyecto es tuyo también! Necesitamos mentes creativas, aportaciones técnicas, ideas frescas y aliados que crean en nuestra misión.

1.  **Explora los Issues:** El mejor lugar para empezar es nuestro [panel de Issues](https://github.com/tu_usuario/finbase/issues). Busca etiquetas como `good first issue` o `help wanted`.
2.  **Abre una Discusión:** Si tienes una idea o una pregunta, abre una [Discusión](https://github.com/tu_usuario/finbase/discussions).
3.  **Envía un Pull Request:**
    -   Haz un fork del repositorio.
    -   Crea una nueva rama para tu funcionalidad (`git checkout -b feature/nombre-feature`).
    -   Haz tus cambios y haz commit (`git commit -m 'feat: Agrega una nueva característica'`).
    -   Empuja tu rama (`git push origin feature/nombre-feature`).
    -   Abre un Pull Request.

Estamos trabajando en una guía de contribución más detallada. Mientras tanto, ¡no dudes en participar!

## 📜 Licencia

Este proyecto se distribuye bajo la **Licencia MIT**. Consulta el archivo [LICENSE](./LICENSE) para más detalles.
```