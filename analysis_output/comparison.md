============================================================
  sonnet  |  model: claude-sonnet-4-6  |  n=98
  total_time=4533.6s  avg=25.6s  min=0.2s  max=124.5s
============================================================
      total_turn_count  total_chars  approx_tokens  truncated  processing_time_s  nodes_extracted  edges_extracted
mean             11.57     62106.39       15526.17       0.12              24.89            19.78            17.26
std              17.52    141106.49       35276.64       0.33              13.38            10.36             8.85
min               1.00        13.00           3.00       0.00               5.62             0.00             0.00
max             102.00    785823.00      196455.00       1.00              64.35            50.00            49.00

[sonnet] Pearson correlation table (traits → outcomes):
                Edges extracted  Nodes extracted  Processing time (s)
Approx tokens             0.402            0.370                0.480
Length (chars)            0.402            0.370                0.480
Turn count                0.574            0.599                0.679
Truncated                 0.382            0.359                0.431

[sonnet] p-values:
                Edges extracted  Nodes extracted  Processing time (s)
Approx tokens            0.0000           0.0002                  0.0
Length (chars)           0.0000           0.0002                  0.0
Turn count               0.0000           0.0000                  0.0
Truncated                0.0001           0.0003                  0.0


============================================================
  haiku  |  model: claude-haiku-4-5-20251001  |  n=100
  total_time=3041.2s  avg=10.7s  min=1.3s  max=45.4s
============================================================
      total_turn_count  total_chars  approx_tokens  truncated  processing_time_s  nodes_extracted  edges_extracted
mean             11.64     61553.12       15387.86       0.12              10.72            15.96            10.95
std              17.45    139799.74       34949.95       0.33               6.71            10.99             6.55
min               1.00        13.00           3.00       0.00               1.33             0.00             0.00
max             102.00    785823.00      196455.00       1.00              45.43            75.00            35.00

[haiku] Pearson correlation table (traits → outcomes):
                Edges extracted  Nodes extracted  Processing time (s)
Approx tokens             0.165            0.041                0.198
Length (chars)            0.165            0.041                0.198
Turn count                0.368            0.320                0.455
Truncated                 0.173            0.035                0.176

[haiku] p-values:
                Edges extracted  Nodes extracted  Processing time (s)
Approx tokens            0.1001           0.6864               0.0478
Length (chars)           0.1002           0.6864               0.0478
Turn count               0.0002           0.0012               0.0000
Truncated                0.0856           0.7287               0.0796


[Model comparison]
  sonnet                Processing time (s)        mean=24.89  std=13.38
  haiku                 Processing time (s)        mean=10.72  std=6.71
  sonnet                Nodes extracted            mean=19.78  std=10.36
  haiku                 Nodes extracted            mean=15.96  std=10.99
  sonnet                Edges extracted            mean=17.26  std=8.85
  haiku                 Edges extracted            mean=10.95  std=6.55


===================================================================
  BELIEF CONTENT ANALYSIS  —  haiku vs. sonnet  (n=100 each)
  Schema: beliefs.py SYSTEM_PROMPT
====================================================================
  Node type  (canonical: claim | evidence | constraint | conclusion)
  Category                        Haiku        Sonnet
  ------------------------ ------------  ------------
  claim                      738 ( 46.2%)     939 ( 48.5%)
  evidence                   595 ( 37.3%)     638 ( 32.9%)
  constraint                 121 (  7.6%)     147 (  7.6%)
  conclusion                 138 (  8.6%)     214 ( 11.0%)
  consequence            *     4 (  0.3%)       0 (  0.0%)
  TOTAL                     1596            1938
  (* off-schema: consequence)
  Node provenance  (canonical: user | model | co-constructed)
  Category                        Haiku        Sonnet
  ------------------------ ------------  ------------
  user                       375 ( 23.5%)     530 ( 27.3%)
  model                     1177 ( 73.7%)    1331 ( 68.7%)
  co-constructed              44 (  2.8%)      77 (  4.0%)
  TOTAL                     1596            1938
  Edge relation  (canonical: supports | tension)
  Category                        Haiku        Sonnet
  ------------------------ ------------  ------------
  supports                   994 ( 90.8%)    1504 ( 88.9%)
  tension                     98 (  8.9%)     187 ( 11.1%)
  example                *     3 (  0.3%)       0 (  0.0%)
  TOTAL                     1095            1691
  (* off-schema: example)
  supports edges → scheme  (causal|evidential|expert|analogical|consequence|example|other)
  Category                        Haiku        Sonnet
  ------------------------ ------------  ------------
  causal                     275 ( 27.7%)     509 ( 33.8%)
  evidential                 443 ( 44.6%)     519 ( 34.5%)
  expert                      18 (  1.8%)      28 (  1.9%)
  analogical                  12 (  1.2%)      29 (  1.9%)
  consequence                 84 (  8.5%)      40 (  2.7%)
  example                     97 (  9.8%)      76 (  5.1%)
  other                       63 (  6.3%)     303 ( 20.1%)
  constraint             *     1 (  0.1%)       0 (  0.0%)
  undercutting           *     1 (  0.1%)       0 (  0.0%)
  TOTAL                      994            1504
  (* off-schema: constraint, undercutting)
  tension edges → attack_type  (canonical: rebutting | undercutting)
  Category                        Haiku        Sonnet
  ------------------------ ------------  ------------
  rebutting                   51 ( 52.0%)      79 ( 42.2%)
  undercutting                46 ( 46.9%)     108 ( 57.8%)
  missing                *     1 (  1.0%)       0 (  0.0%)
  TOTAL                       98             187
  (* off-schema: missing)
--------------------------------------------------------------------
  KEY RATES
  Metric                                             Haiku    Sonnet
  ----------------------------------------------- --------  --------
  Convs with ≥1 co-constructed node  (count)            16        20
  Convs with ≥1 co-constructed node  (%)              16.0      20.0
  Convs with ≥1 tension edge  (count)                   61        76
  Convs with ≥1 tension edge  (%)                     61.0      76.0
  % of all edges that are tension                      8.9      11.1
  Mean nodes per conversation                         16.0      19.4
  Mean edges per conversation                         10.9      16.9
  Mean co-constructed nodes per conv                   0.4       0.8
  Mean tension edges per conv                          1.0       1.9