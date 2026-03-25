## The UAHP Agentic Stack

Four layers. One complete infrastructure for the agentic web.
```mermaid
flowchart TD
    R["UAHP-Registry\nDiscovery Layer\nFind agents by capability + energy profile"]
    U["UAHP v0.5.4\nTrust & Authentication\nWho you are — identity, liveness, transport"]
    S["SMART-UAHP\nThermodynamic Routing\nWhere you think — carbon-aware substrate selection"]
    C["CSP\nCognitive State Protocol\nWhat you are thinking — portable semantic state"]

    R --> U
    U --> S
    S --> C
```

| Layer | Repo | Role |
|-------|------|------|
| Discovery | UAHP-Registry | Find agents by capability and energy profile |
| Trust | UAHP v0.5.4 | Identity, liveness proofs, signed handshakes |
| Routing | SMART-UAHP | Carbon-aware substrate selection |
| State | CSP | Portable semantic state transfer |


# UAHP-Registry
Thermodynamic-aware, liveness-native discovery layer for the UAHP agentic stack
