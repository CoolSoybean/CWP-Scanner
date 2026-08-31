# File manifest

```text
CWP-Scanner/
├── .env.example
├── AGENTS.md
├── .github/workflows/
│   ├── parity_test.yml
│   ├── scan_hs300.yml
│   └── scan_sp500.yml
├── ARCHITECTURE.md
├── MANIFEST.md
├── PROJECT_CONTEXT.md
├── README.md
├── config/
│   ├── markets.yml
│   └── scanner.yml
├── docs/
│   └── PORTING_NOTES.md
├── data/
│   ├── __init__.py
│   ├── base.py
│   ├── data_cn.py
│   └── data_us.py
├── engine/
│   ├── __init__.py
│   ├── cwp_engine.py
│   ├── market_profiles.py
│   └── models.py
├── notification/
│   ├── __init__.py
│   ├── email.py
│   ├── notifier.py
│   └── telegram.py
├── parity/
│   ├── __init__.py
│   ├── compare_outputs.py
│   ├── parity_test.py
│   └── fixtures/
│       ├── expected_signals.csv
│       └── pine_export.csv
├── reference/
│   └── CWP1.8.5.pine.txt
├── scanner/
│   ├── __init__.py
│   ├── ranking.py
│   ├── result_builder.py
│   └── scanner.py
├── scripts/
│   ├── smoke_test.py
│   └── source_parity_smoke.py
├── tests/
│   ├── conftest.py
│   ├── test_data_base.py
│   ├── test_engine.py
│   ├── test_notifier.py
│   ├── test_parity.py
│   ├── test_source_state_machine.py
│   └── test_watchlist.py
├── watchlist/
│   ├── __init__.py
│   └── watchlist_state.py
├── cache/
│   └── constituents/
├── logs/
├── output/
│   ├── alerts/
│   ├── latest/
│   └── reports/
├── state/
├── pyproject.toml
└── requirements.txt
```
