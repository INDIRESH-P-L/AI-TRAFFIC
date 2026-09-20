# TRAFFICINTEL AI
## Real-Time AI Traffic Intelligence & Adaptive Signal Management Platform
*REAL-TIME INTELLIGENCE FOR SAFER, SMARTER TRAFFIC*

---

## 1. Executive Summary

**TRAFFICINTEL AI** is a serious, production-grade Intelligent Transportation System (ITS) platform engineered for municipal traffic management centers and regional transportation authorities.

### Core Architectural Guarantees:
- **Zero Fake Data**: Strictly zero synthetic vehicle counts, zero fake camera streams, zero random generators (`Math.random()`), zero mock incident feeds, and zero "demo/simulation modes".
- **Truthful Telemetry States**: When data sources are unconfigured or disconnected, the system explicitly reports:
  - `SYSTEM READY - No traffic infrastructure is currently connected.`
  - `NO CAMERA CONNECTED`
  - `NO SENSOR DATA AVAILABLE`
  - `SIGNAL CONTROLLER: NOT CONNECTED`
  - `SIGNAL STATE: UNAVAILABLE`
  - `WEATHER DATA UNAVAILABLE`
  - `INSUFFICIENT DATA FOR RELIABLE FORECAST`
- **Deterministic Signal Safety Engine**: All signal control commands pass through mathematical validation enforcing NEMA TS 2 / 170 / 2070 dual-ring barrier conflict matrices, minimum/maximum green times, yellow change intervals, all-red clearance, and command freshness (<5.0s window). AI and operators can never override this safety layer.
- **Provider Architecture**: Real adapters for `SignalControllerProvider` (TCP/IP socket & NTCIP 1202), `CameraProvider` (RTSP & ONVIF reachability), `TrafficSensorProvider` (radar, loop, microwave), and `WeatherProvider` (Open-Meteo GIS).
- **Grounded Operations AI Copilot**: LLM assistant querying live database state and indexed engineering standards (FHWA MUTCD Section 4D, NEMA TS 2, municipal SOPs). If an unobserved junction is queried, it truthfully states no live telemetry exists.
- **Human-Engineered Operations Console**: Restrained, high-density ITS console with 20 dedicated routes built in React, TypeScript, Leaflet GIS, and custom CSS design tokens.

---

## 2. System Architecture

```
                                  +--------------------------------------------------------+
                                  |              TRAFFICINTEL AI Web Console               |
                                  |       (React + TypeScript + Vite + Leaflet GIS)        |
                                  +---------------------------+----------------------------+
                                                              | HTTPS / WSS
                                                              v
+------------------------------------------------------------------------------------------+
|                                    API Gateway & Services (FastAPI)                      |
|  +---------------------+   +---------------------+   +--------------------------------+  |
|  | Auth & RBAC         |   | Real-Time Event Bus |   | Audit Logger & Trace Engine    |  |
|  | (JWT / API Keys)    |   | (WebSocket Manager) |   | (Immutable Action Ledger)      |  |
|  +---------------------+   +---------------------+   +--------------------------------+  |
|                                                                                          |
|  +------------------------------------------------------------------------------------+  |
|  |                               Core Domain Services                                 |  |
|  |  * Traffic State & Provenance Engine     * Data Quality & Freshness Engine         |  |
|  |  * Incident Detection & Lifecycle Engine * Sensor Fusion Engine (Kalman/Weighted)  |  |
|  |  * Real Computer Vision Frame Pipeline   * Explainable AI Signal Optimizer         |  |
|  |  * Grounded LLM Operations Copilot (RAG) * Telemetry Ingestion Hub                 |  |
|  +-------------------------------------------+----------------------------------------+  |
|                                              |                                           |
|                                              v                                           |
|  +------------------------------------------------------------------------------------+  |
|  |                      DETERMINISTIC SIGNAL SAFETY ENGINE                            |  |
|  |  * Phase Conflict Matrix Check            * Min/Max Green Interval Verification    |  |
|  |  * Yellow Change & All-Red Clearance      * Pedestrian Walk & Clearance (FDW)     |  |
|  |  * Command Freshness (<5s window)         * Idempotency & Concurrency Validation   |  |
|  |  * Controller Capability Verification     * Hardware Operational State Lock        |  |
|  +-------------------------------------------+----------------------------------------+  |
|                                              | Verified Command Only                     |
|                                              v                                           |
|  +------------------------------------------------------------------------------------+  |
|  |                         Provider Abstraction & Adapter Layer                       |  |
|  |  * SignalControllerProvider (NTCIP 1202 SNMP, ASC/3 Ethernet, REST/Socket)        |  |
|  |  * CameraProvider (RTSP / ONVIF / Edge Ingest / Network Camera Test)              |  |
|  |  * TrafficSensorProvider (Radar, Induction Loop, Microwave, Roadside IoT)          |  |
|  |  * WeatherProvider (Real Open-Meteo GIS Ingestion & API adapters)                  |  |
|  |  * TransitProvider (GTFS & GTFS-Realtime) / EmergencyDataProvider                 |  |
|  +-------------------------------------------+----------------------------------------+  |
+----------------------------------------------+-------------------------------------------+
                                               |
                                               v
+------------------------------------------------------------------------------------------+
|                             Storage & Persistence Layer                                  |
|  * PostgreSQL + PostGIS (Production) / Dual-Dialect SQLAlchemy 2.0 Engine                |
|  * Schema of 30+ normalized domain tables with Source Provenance & Data Quality stamps   |
|  * Clean initial state: zero fake operational records, zero seeded traffic numbers       |
+------------------------------------------------------------------------------------------+
```

---

## 3. Quick Start & Execution

### Prerequisites
- Python 3.12+
- Node.js v20+ and npm

### 1. Backend Setup & Run
```bash
cd backend
python -m pip install -r requirements.txt

# Bootstrap clean database (creates tables & initial administrator)
python -m app.db_init

# Launch API server
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Backend will be active at `http://127.0.0.1:8000`. OpenAPI docs available at `http://127.0.0.1:8000/docs`.

### 2. Frontend Setup & Run
```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```
Frontend console will be active at `http://127.0.0.1:5173`.

### 3. Default Credentials
- **Username**: `admin`
- **Password**: `TrafficIntel2026!`
- **Role**: `ADMIN`

---

## 4. Automated Test Suite

Run the automated pytest suite:
```bash
cd backend
python -m pytest -v
```

All 11 tests validate deterministic safety, data quality transitions, and zero-fake-data invariants:
- Conflict matrix rejection of concurrent conflicting greens
- Minimum green active phase hold enforcement
- Stale command expiration protection (<5.0s window)
- Disconnected hardware command lock
- Quality state transitions (`FRESH` → `AGING` → `STALE` → `DISCONNECTED`)
- Grounded Copilot response verification

---

## 5. Running the Application

### Start Backend API Server
```bash
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Start Frontend Application
```bash
cd frontend
npm run dev
```

The application will be accessible at:
- **Web Console**: `http://127.0.0.1:5173`
- **REST API Docs**: `http://127.0.0.1:8000/docs`
- **Default Operator**: `admin` / `TrafficIntel2026!`

