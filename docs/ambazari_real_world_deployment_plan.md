# Real-World Deployment Plan: FlowGuard at Ambazari Lake & Nag River, Nagpur

## 1. Executive Summary
The Ambazari Lake and its primary outflow, the Nag River, present a critical urban flooding challenge for Nagpur. With drainage infrastructure historically designed for 60mm/hr rainfall, recent climate-induced extreme weather has consistently overwhelmed the system. Exacerbating this issue are acute drainage blockages caused by *Eichhornia* (water hyacinth) mats, construction debris, and urban encroachment. 

This document outlines a realistic, phased deployment plan for **FlowGuard**—an IoT-based blockage detection and flood early warning system—to monitor the Ambazari Lake overflow points and the Nag River catchment area. The goal is to transition from reactive crisis management (post-flood pumping and manual cleaning) to proactive, predictive maintenance and early warning.

## 2. Site Analysis & Challenges

### 2.1 The Hydrological Context
*   **Source:** Ambazari Lake overflow.
*   **Primary Channel:** Nag River and connected nullahs (stormwater drains).
*   **Vulnerable Zones:** Low-lying residential areas including Ambazari Layout, Samta Nagar, and Daga Layout.
*   **Current Mitigation:** Nagpur Municipal Corporation (NMC) relies on controlled discharge, high-capacity pumps during crises, and pre-monsoon desilting.

### 2.2 Root Causes of Blockages
1.  **Organic Debris:** Dense water hyacinth mats that rapidly accumulate at culverts and bridge pillars.
2.  **Inorganic Debris:** Solid waste, plastic pollution, and construction debris from ongoing urban projects.
3.  **Siltation:** Reduced channel capacity due to sediment buildup.

## 3. FlowGuard Network Architecture for Ambazari

FlowGuard's low-cost ($5-$10 per node) architecture allows for high-density deployment, creating a granular monitoring network rather than relying on a few expensive sensors.

### 3.1 Sensor Node Deployment Strategy
We will deploy **ESP32 + HC-SR04** ultrasonic sensor nodes across three distinct zones:

*   **Zone 1: The Source (Ambazari Dam Overflow & Spillway)**
    *   **Objective:** Monitor the initial discharge volume and lake level.
    *   **Placement:** 3-5 nodes along the main spillway and primary exit culverts.
    *   **Function:** Establish the baseline inflow ($Q_{in}$) for the downstream network.

*   **Zone 2: Critical Bottlenecks (Nag River Bridges & Culverts)**
    *   **Objective:** Detect blockages caused by water hyacinths and debris.
    *   **Placement:** 15-20 nodes strategically mounted under bridges (e.g., near Ambazari Layout and Samta Nagar) and at major nullah junctions.
    *   **Function:** Measure water height ($h$) to calculate the discharge coefficient ($C_d$) in real-time, identifying physical obstructions.

*   **Zone 3: Vulnerable Catchment Areas (Low-lying Layouts)**
    *   **Objective:** Validate cascade effects and trigger localized warnings.
    *   **Placement:** 10 nodes in street-level storm drains in Daga Layout and surrounding areas.

### 3.2 Hardware Hardening for Real-World Conditions
The standard ESP32+HC-SR04 setup must be adapted for harsh environments:
*   **Enclosures:** IP67-rated waterproof housing for all electronics.
*   **Power:** Solar panels (5W) with 18650 Li-ion battery backups to ensure operation during power grid failures (common during storms).
*   **Connectivity:** LoRaWAN gateways (or cellular LTE-M where LoRa is unavailable) to transmit data reliably when local Wi-Fi networks fail during floods.

## 4. Software & Analytics Integration

### 4.1 Physics-Based Detection in the Wild
*   **Calibration:** Each sensor node location will require initial baseline calibration during dry and standard flow conditions to establish the "clean" state discharge coefficient ($C_d$).
*   **Dynamic Modeling:** FlowGuard's core orifice equation ($Q = C_d \times A \times \sqrt{2gh}$) will run continuously. A sudden drop in calculated $C_d$ relative to the upstream flow will flag a potential blockage (e.g., hyacinth mat accumulation).

### 4.2 ML Confirmation (Isolation Forest)
*   Because real-world rivers have turbulence and sensor noise, the ML layer will filter out anomalies (like a passing log) from sustained blockage trends (a growing debris dam). 
*   It requires at least 2 weeks of baseline data post-installation to reliably distinguish noise from genuine blockage patterns.

### 4.3 Network Cascade Simulation (Muskingum Routing)
*   **Predictive Routing:** Using Muskingum routing, FlowGuard will model how a blockage at Zone 2 (a clogged bridge near Ambazari Layout) will back up water into Zone 3 (Daga Layout streets).
*   **Lead Time:** The system aims to provide NMC authorities with a 2 to 4-hour lead time regarding where flood waters will crest based on current blockage severity.

## 5. Phased Implementation Timeline

### Phase 1: Pilot & Calibration (Months 1-2)
*   **Action:** Deploy 5 hardened nodes at the most notorious bottleneck near Ambazari Layout.
*   **Goal:** Calibrate sensors, test solar power reliability, and build the initial ML baseline data. No automated alerts will be sent to the public during this phase.

### Phase 2: Network Expansion (Months 3-4)
*   **Action:** Scale to 30 nodes covering the Nag River stretch up to Samta Nagar and Daga Layout.
*   **Goal:** Connect the nodes to the central FlowGuard Streamlit dashboard. Begin testing the Muskingum routing cascade model against real-world rainfall events.

### Phase 3: NMC Integration & Alerting (Months 5-6)
*   **Action:** Integrate FlowGuard's SQLite audit trail and dashboard with the NMC's emergency response center.
*   **Goal:** Enable automated maintenance dispatch. When FlowGuard detects a 60% blockage trend at a specific culvert due to hyacinths, a work order is generated for targeted cleaning *before* the next rainfall.

## 6. Maintenance & Sustainability

To ensure long-term viability:
*   **Civic Accountability:** The SQLite audit trail will log every detected blockage and the corresponding NMC response time, providing transparency.
*   **Sensor Cleaning:** Ultrasonic sensors require periodic wiping to remove condensation, cobwebs, or mud. A monthly maintenance schedule will be integrated into existing NMC sweeping routes.
*   **Community Integration:** Involve local residents in Ambazari Layout to host LoRaWAN gateways or report visual confirmations of system alerts.

## 7. Conclusion
Deploying FlowGuard at Ambazari Lake shifts Nagpur's flood management from reactive pumping to proactive network monitoring. By pinpointing exact blockage locations (like hyacinth buildup at specific bridges) in real-time, the NMC can deploy targeted clearing operations, drastically reducing the impact of extreme rainfall on vulnerable neighborhoods.
