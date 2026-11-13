# Uses of the held-out validation clips

Every validation run that scores clips of a `holdout*` group is added here by `funscript-gen validate` (the purpose is
`--purpose`). Each look at held-out scores leaks a little into the decisions made from them, so the count is the
point: confirm a change once at the end, and put new clips into the held-out groups first. Runs before 2026-11-12
were not recorded (the development logs in PLAN.md and docs/archive/PLAN-archive.md mention them).

| date | run | groups: clips | purpose |
| --- | --- | --- | --- |
| 2026-11-12 | full-1112 | holdout: A08 C02 C03 D04 D05 M01 N01; holdout2: B05 B06 P01 P02 P03 R01 T01 V01 X01 Z01 AB01 AD01 AF01 AF02 AF03 AH01 AH02 AJ01 AL01 AN01 AP01 AR01 AR02 AT01 AV01 | B1: the same-source baseline of all 78 clips (default, user, noai); later runs of this day were recorded as they were made |
| 2026-11-12 | a1-review | holdout: A08 C02 C03 D04 D05 M01 N01; holdout2: B05 B06 P01 P02 P03 R01 T01 V01 X01 Z01 AB01 AD01 AF01 AF02 AF03 AH01 AH02 AJ01 AL01 AN01 AP01 AR01 AR02 AT01 AV01 | A1: replay of full-1112 to score the review order (first quarter of the review order); output unchanged |
| 2026-11-12 | rot1 | holdout2: AD01 | C4: video rotation fix, check of a holdout2 clip that has a rotation (the other one is in rot2) |
| 2026-11-12 | rot2 | holdout2: B06 | C4: video rotation fix, the other clip with a rotation |
| 2026-11-12 | noise-1112 | holdout: A08 C02 C03 D04 D05 M01 N01; holdout2: B05 B06 P01 P02 P03 R01 T01 V01 X01 Z01 AB01 AD01 AF01 AF02 AF03 AH01 AH02 AJ01 AL01 AN01 AP01 AR01 AR02 AT01 AV01 | B2: same code as full-1112 with an empty AI cache (noise floor), also checks this day's changes |
| 2026-11-13 | hashchk | holdout: A08 C02 C03 D04 D05 M01 N01; holdout2: B05 B06 P01 P02 P03 R01 T01 V01 X01 Z01 AB01 AD01 AF01 AF02 AF03 AH01 AH02 AJ01 AL01 AN01 AP01 AR01 AR02 AT01 AV01 | video identity by content hash: --replay of full-1112 to check the old analysis files still load and the output is unchanged (not used to choose anything) |
