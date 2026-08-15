# Future Leak Audit

Files scanned: 9
Rows checked: 4193
Future leaks: 1

## Findings

| file                     | trigger_time        | analysis_as_of      |   symbol | field       |   field_value | parsed              | leak   | note             |
|:-------------------------|:--------------------|:--------------------|---------:|:------------|--------------:|:--------------------|:-------|:-----------------|
| 2026-08-08_20-20-46.json | 2026-08-08 20:20:46 | 2026-08-08 20:20:46 | 20260810 | report_date |      20260810 | 2026-08-10 00:00:00 | YES    | future timestamp |