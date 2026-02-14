# How To Trade Options with Alpaca's Dashboard and Trading API

Author: Satoshi Ido  
Last Updated: August 15, 2025  
Source: Alpaca Learn

---

## Overview

Alpaca enables developers to algorithmically trade options, stocks, ETFs, and crypto, with both manual and automated execution. The platform supports paper trading, live trading, and advanced multi-leg options strategies such as:

- Straddles
- Strangles
- Iron butterflies
- Iron condors
- Credit, calendar, and debit spreads

These multi-leg strategies allow simultaneous execution of multiple contracts, improving efficiency and risk management.

---

## Before You Begin

Recommended prerequisites:
- Alpaca Trading API account
- API key setup
- Paper trading environment
- TradingView integration (optional)
- Options trading approval level

Paper trading accounts automatically have Level 3 strategy access.

---

## Part 1: Apply for Options Trading

### 1. Sign Up
Create an Alpaca Trading API account.  
Live accounts require additional background and investment objective information.

### 2. Apply for Options Access
- Go to **Home**
- Click “Apply for Options Trading”
- Or check under:  
  `Account → Configure`

Make sure you check the correct environment (Live vs Paper).

### 3. Get Approved
Once approved, you can trade options via:
- Alpaca Dashboard
- Trading API

---

## Part 2: Trading Options Using the Dashboard

### Step 1: Log In
Navigate to the Home page after signing in.

### Step 2: Select Account
Choose between:
- Paper Trading (risk-free testing)
- Live Trading (real capital)

### Step 3: Find an Options Contract
- Search underlying asset (e.g., SPY)
- Toggle from **Stocks → Options**
- Choose:
  - Calls or Puts
  - Expiration date (0DTE to long-term)

### Step 4: Place an Order
Select:
- Order type (Market, Limit, Stop, etc.)
- Number of contracts  
Then click **Confirm Order**.

---

## Exercising an Option

Exercising means using the contract’s right to buy or sell the underlying asset at the strike price.

Steps:
1. Go to “Home” or “Positions”
2. Select the contract
3. Click **Exercise**
4. Confirm

Notes:
- Requires sufficient funds
- American-style options can be exercised anytime before expiration

---

## Closing an Options Position

To close a position:
- Sell a long contract
- Buy back a short contract

Steps:
1. Go to “Home” or “Positions”
2. Select the contract
3. Click **Close Position**
4. Confirm

---

## Multi-Leg Options Strategies (Dashboard)

Example: Long Straddle  
- Buy 1 Call + Buy 1 Put  
- Same strike price  
- Same expiration

Key rules:
- Up to four legs per strategy
- Cannot cancel individual legs
- Must cancel or replace the entire order

To close a multi-leg position:
- Go to Positions
- Select contracts
- Click **Liquidate Selected**

---

## Part 3: Algorithmic Options Trading with Alpaca-py

### Installation

```bash
pip install alpaca-py --upgrade
````

### Required Imports

```python
import json
import os
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, OrderType, TimeInForce
```

---

## Setup Trading Client

```python
load_dotenv()

TRADE_API_KEY = os.environ.get('ALPACA_API_KEY')
TRADE_API_SECRET = os.environ.get('ALPACA_SECRET_KEY')

trade_client = TradingClient(
    api_key=TRADE_API_KEY,
    secret_key=TRADE_API_SECRET,
    paper=True
)
```

---

## Retrieve Option Contracts

```python
from alpaca.trading.requests import GetOptionContractsRequest

req = GetOptionContractsRequest(
    underlying_symbol=["SPY"]
)

res = trade_client.get_option_contracts(req)
```

You can filter contracts by:

* Expiration date range
* Strike price range
* Option type (Call/Put)
* Exercise style (American/European)

---

## Place a Long Put or Call Order

```python
req = MarketOrderRequest(
    symbol="OPTION_SYMBOL",
    qty=1,
    side=OrderSide.BUY,
    type=OrderType.MARKET,
    time_in_force=TimeInForce.DAY
)

trade_client.submit_order(req)
```

Important:

* On expiration day, orders must be submitted before 3:15 p.m. ET
* Expiring positions may be auto-liquidated for risk management

---

## Monitoring Positions

```python
positions = trade_client.get_all_positions()
print(positions)
```

Check:

* Cost basis
* Unrealized P/L
* Open positions by symbol or contract ID

---

## Closing an Option Position via API

```python
trade_client.close_position(
    symbol_or_asset_id="OPTION_SYMBOL"
)
```

---

## Market Data (Options)

Available data endpoints:

* Latest quotes
* Latest trades
* Option chains
* Historical bars
* Live data streams

---

## Multi-Leg Orders via API (Example: Long Straddle)

```python
from alpaca.trading.requests import OptionLegRequest
from alpaca.trading.enums import OrderClass

order_legs = [
    OptionLegRequest(symbol="CALL_SYMBOL", side=OrderSide.BUY, ratio_qty=1),
    OptionLegRequest(symbol="PUT_SYMBOL", side=OrderSide.BUY, ratio_qty=1)
]

req = MarketOrderRequest(
    qty=1,
    order_class=OrderClass.MLEG,
    time_in_force=TimeInForce.DAY,
    legs=order_legs
)

trade_client.submit_order(req)
```

---

## Using Postman for Options Trading API

### Environment Variables

* `api_key`
* `secret_key`
* `base_url`:

  * Paper: [https://paper-api.alpaca.markets/v2](https://paper-api.alpaca.markets/v2)
  * Live: [https://api.alpaca.markets](https://api.alpaca.markets)

### Authentication Headers

* APCA-API-KEY-ID
* APCA-API-SECRET-KEY

---

## Key API Endpoints

### Check Account

```
GET {{base_url}}/account
```

### Get Assets (Options Enabled)

```
GET {{base_url}}/assets?status=active&asset_class=us_equity
```

### Get Option Chains

```
GET https://data.alpaca.markets/v1beta1/options/snapshots/SPY
```

### Place Order

```
POST {{base_url}}/orders
```

### Monitor Orders

```
GET {{base_url}}/orders
GET {{base_url}}/positions
```

---

## Risk Disclaimer

Options trading carries significant risk and is not suitable for all investors.
Paper trading does not involve real money and is for simulation purposes only.

All investments involve risk, and past performance does not guarantee future results.

