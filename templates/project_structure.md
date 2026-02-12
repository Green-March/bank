# Project Structure (Per Ticker/Request)

```
projects/{ticker_or_request_id}/
  context.md
  notes/
  reports/
    report.md
    report.html
  figures/
  logs/
    analysis_log.md
  sources/
    source_index.csv
```

Data pipeline outputs:

```
data/{ticker}/
  raw/
    jquants/
    edinet/
  parsed/
    financials.json
    metrics.json
  reports/
    {ticker}_report.md
    {ticker}_report.html
```
