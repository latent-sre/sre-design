# Resolver-backed cross-file call view

Scope: conservative statically resolved production call edges; not runtime traces.

```mermaid
flowchart LR
  n_376b90311d4c["sre-kb / sre_kb.atlas"]
  n_76e7d067d8d4["sre-kb / sre_kb.cli"]
  n_a1b04e1510ea["sre-kb / sre_kb.collectors"]
  n_7fa74111c91a["sre-kb / sre_kb.config"]
  n_d9407297eab9["sre-kb / sre_kb.estate"]
  n_ab9cb5f52694["sre-kb / sre_kb.flow"]
  n_5db1217d1f10["sre-kb / sre_kb.inventory_signatures"]
  n_07be103af52e["sre-kb / sre_kb.models"]
  n_2b2ef8c2af4a["sre-kb / sre_kb.parsing"]
  n_521acd5fb24b["sre-kb / sre_kb.pipeline"]
  n_23e1854344b3["sre-kb / sre_kb.publish"]
  n_1fd35c32c66a["sre-kb / sre_kb.registry"]
  n_05130caebc6f["sre-kb / sre_kb.render"]
  n_721ee922c255["sre-kb / sre_kb.reporting"]
  n_58702e1831b4["sre-kb / sre_kb.scan_plan"]
  n_17e7ed814d9d["sre-kb / sre_kb.scoring"]
  n_9a916b245e23["sre-kb / sre_kb.signatures"]
  n_4b0471fcd10a["sre-kb / sre_kb.synth"]
  n_81553fefe625["sre-kb / sre_kb.taxonomy"]
  n_898f211025a0["sre-kb / sre_kb.tiers"]
  n_19fa77dc1e88["sre-kb / sre_kb.util"]
  n_1af9ff020e7c["sre-kb / sre_kb.validation"]
  n_376b90311d4c -->|1 call(s)| n_a1b04e1510ea
  n_376b90311d4c -->|3 call(s)| n_2b2ef8c2af4a
  n_76e7d067d8d4 -->|1 call(s)| n_7fa74111c91a
  n_a1b04e1510ea -->|1 call(s)| n_5db1217d1f10
  n_a1b04e1510ea -->|31 call(s)| n_07be103af52e
  n_a1b04e1510ea -->|5 call(s)| n_9a916b245e23
  n_a1b04e1510ea -->|1 call(s)| n_81553fefe625
  n_a1b04e1510ea -->|24 call(s)| n_19fa77dc1e88
  n_d9407297eab9 -->|2 call(s)| n_a1b04e1510ea
  n_d9407297eab9 -->|1 call(s)| n_7fa74111c91a
  n_d9407297eab9 -->|1 call(s)| n_5db1217d1f10
  n_d9407297eab9 -->|1 call(s)| n_05130caebc6f
  n_d9407297eab9 -->|1 call(s)| n_4b0471fcd10a
  n_d9407297eab9 -->|2 call(s)| n_19fa77dc1e88
  n_d9407297eab9 -->|4 call(s)| n_1af9ff020e7c
  n_ab9cb5f52694 -->|1 call(s)| n_07be103af52e
  n_ab9cb5f52694 -->|1 call(s)| n_19fa77dc1e88
  n_521acd5fb24b -->|23 call(s)| n_a1b04e1510ea
  n_521acd5fb24b -->|3 call(s)| n_7fa74111c91a
  n_521acd5fb24b -->|2 call(s)| n_07be103af52e
  n_521acd5fb24b -->|1 call(s)| n_05130caebc6f
  n_521acd5fb24b -->|2 call(s)| n_721ee922c255
  n_521acd5fb24b -->|5 call(s)| n_17e7ed814d9d
  n_521acd5fb24b -->|1 call(s)| n_9a916b245e23
  n_521acd5fb24b -->|9 call(s)| n_4b0471fcd10a
  n_521acd5fb24b -->|1 call(s)| n_898f211025a0
  n_521acd5fb24b -->|5 call(s)| n_19fa77dc1e88
  n_521acd5fb24b -->|13 call(s)| n_1af9ff020e7c
  n_23e1854344b3 -->|1 call(s)| n_7fa74111c91a
  n_23e1854344b3 -->|1 call(s)| n_05130caebc6f
  n_23e1854344b3 -->|1 call(s)| n_898f211025a0
  n_1fd35c32c66a -->|1 call(s)| n_7fa74111c91a
  n_05130caebc6f -->|1 call(s)| n_1fd35c32c66a
  n_05130caebc6f -->|1 call(s)| n_81553fefe625
  n_05130caebc6f -->|1 call(s)| n_898f211025a0
  n_05130caebc6f -->|2 call(s)| n_19fa77dc1e88
  n_721ee922c255 -->|1 call(s)| n_05130caebc6f
  n_721ee922c255 -->|1 call(s)| n_898f211025a0
  n_58702e1831b4 -->|1 call(s)| n_7fa74111c91a
  n_17e7ed814d9d -->|1 call(s)| n_5db1217d1f10
  n_4b0471fcd10a -->|2 call(s)| n_a1b04e1510ea
  n_4b0471fcd10a -->|1 call(s)| n_7fa74111c91a
  n_4b0471fcd10a -->|1 call(s)| n_5db1217d1f10
  n_4b0471fcd10a -->|1 call(s)| n_07be103af52e
  n_4b0471fcd10a -->|1 call(s)| n_2b2ef8c2af4a
  n_4b0471fcd10a -->|2 call(s)| n_05130caebc6f
  n_4b0471fcd10a -->|4 call(s)| n_17e7ed814d9d
  n_4b0471fcd10a -->|1 call(s)| n_9a916b245e23
  n_4b0471fcd10a -->|2 call(s)| n_19fa77dc1e88
  n_81553fefe625 -->|1 call(s)| n_7fa74111c91a
  n_1af9ff020e7c -->|1 call(s)| n_a1b04e1510ea
  n_1af9ff020e7c -->|1 call(s)| n_7fa74111c91a
  n_1af9ff020e7c -->|1 call(s)| n_521acd5fb24b
  n_1af9ff020e7c -->|1 call(s)| n_9a916b245e23
```
