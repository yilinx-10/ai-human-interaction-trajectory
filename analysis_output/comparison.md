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