<p class="project-kicker">Cloud delivery / Ownership</p>

# Deploy without undoing each other's changes.

<p class="project-lead">Infrastructure and application teams share one ECS service. An explicit ownership contract keeps their deployments from overwriting each other's configuration.</p>

## How it works

```mermaid
---
config:
  theme: base
  themeVariables:
    primaryTextColor: '#183452'
    textColor: '#183452'
    lineColor: '#7b8797'
    edgeLabelBackground: '#e8effa'
    fontFamily: 'Arial, sans-serif'
    fontSize: '15px'
  flowchart:
    nodeSpacing: 24
    rankSpacing: 28
    padding: 12
---
flowchart TB
    accTitle: Two deployment writers share an explicit ownership contract
    accDescr: Infrastructure owns roles, networking and service resources. The application owns its image and runtime settings. The contract validates configuration and participating writers serialize deployments before updating ECS.
    I["Infrastructure<br/>Roles / network / service"] --> C["Ownership contract<br/>Validate each team's fields"]
    A["Application<br/>Image / runtime settings"] --> C
    C --> L["Shared deployment lock<br/>Participating writers take turns"]
    L --> E["Amazon ECS service"]
    classDef source fill:#e8effa,stroke:#5276a2,color:#183452,stroke-width:1.5px
    classDef core fill:#e0f3ec,stroke:#328267,color:#173f33,stroke-width:1.5px
    classDef limit fill:#fff0dc,stroke:#b27b36,color:#63421d,stroke-width:1.5px
    class I,A source
    class C,L core
    class E limit
```

[Check locally](demo.md){ .overview-link }
[Ownership and migration](migration.md){ .overview-link }
[Deployment locking](serialization.md){ .overview-link }

!!! note "Scope"
    Local checks are verified. A real AWS deployment still requires a selected personal account and region. Every writer must use the lock.
