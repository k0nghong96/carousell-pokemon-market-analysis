# 📊 Carousell Pokémon TCG Secondary Market Analysis & Web Scraper

An end-to-end data pipeline, statistical analysis, and machine learning study of **2,968 active Pokémon TCG listings** on Carousell Malaysia. 

This repository includes both the **automated Playwright scraper** used to collect real-time marketplace data and the **Random Forest ML pipeline** used to evaluate seller behaviors, posting timing, and price drivers.

---

## 📸 Market & Model Visualizations

### 1. Marketplace Summary Dashboard
![Market Analysis Dashboard](images/carousell_pokemon_market_dashboard.png)

### 2. Predictive Model Testing & Validation
![Model Validation Dashboard](images/model_testing_validation_dashboard.png)

---

## 🚀 Repository Features

* **Async Playwright Web Scraper (`scraper.py`):**
  * Supports both **Surface Mode** (high-speed search result pagination) and **Deep Mode** (detailed listing page visits).
  * Automated price sanitization, junk price filter detection (`RM 123456`, `RM 99999`), and temporal offset parsing (`posted_hours_ago`).
  * Includes auto-recovery checkpointing and pop-up handling.

* **Market Analysis & Machine Learning (`analysis.py`):**
  * **Temporal Analysis:** Analyzes listing volume vs. price variance across days of the week.
  * **Seller Concentration:** Tracks portfolio GMV across power seller accounts.
  * **Random Forest Regressor:** Models price drivers on $\ln(1 + \text{price})$ with feature permutation testing.

---

## 🔑 Key Analytical Findings

1. **Sunday Supply Dump vs. Weekday Value:**
   * **Sunday** accounts for **26.6% of total listing volume** (790 listings) but drops to the lowest median price (**RM 16.00**).
   * High-value listings concentrate on **Mondays** (median **RM 80.00**) and **Fridays** (median **RM 75.00**).

2. **Capital Dominance:**
   * **7.3% of top sellers control over 53%** of all active listed capital (~RM 660,000+).

3. **Statistically Tested Price Drivers:**
   * **PSA Grading (`kw_PSA`):** Accounts for **24.2% of relative predictive importance** in price determination.
   * **Character Tax:** `Charizard` (**RM 250.00 median**) and `Pikachu` (**RM 125.00 median**) command strong price multipliers over generic Pokémon cards (**RM 30.00 median**).

---

## 🛠️ Setup & Execution

### 1. Clone & Install
```bash
git clone [https://github.com/YOUR_USERNAME/carousell-pokemon-market-analysis.git](https://github.com/YOUR_USERNAME/carousell-pokemon-market-analysis.git)
cd carousell-pokemon-market-analysis
pip install -r requirements.txt
playwright install chromium
```

### 2. Run the Scraper
```bash
python scraper.py
```

### 3. Run the Market Analysis & Model
```bash
python analysis.py
```