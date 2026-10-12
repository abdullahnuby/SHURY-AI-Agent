# Personal Agent V11 Architecture

```text
USER / EVENT
   |
   v
UNDERSTANDING
   |
   +--> DATA INTENT -------------------+
   |                                   |
   +--> TASK / ACTION                  v
           |                    DATA EVIDENCE ENGINE
           v                    - schema
   GOAL / CONSTRAINTS             - quality
           |                      - statistics
           v                      - relationships
   HIERARCHICAL PLANNER            - anomalies
           |                      - trends
           v                      - comparison / drift
   PLAN CERTIFICATE                       |
           |                               v
           v                         VERIFIED EVIDENCE
     POLICY / APPROVAL                     |
           |                                +------+
           v                                       |
       EXECUTION <---- WORLD STATE <---- MEMORY / EXPERIENCE
           |
           v
      VERIFICATION
           |
           v
     EFFECT / CHECKPOINT
           |
           +----> SELF-ANALYTICS
                    - latency
                    - failures
                    - retries
                    - horizon survival
                    - degradation alerts
```

V11 treats data analysis as another first-class capability of the agent, with
read-only, reproducible, fingerprinted evidence. The same runtime remains
model-free and provider-free.
