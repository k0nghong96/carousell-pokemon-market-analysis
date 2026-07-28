import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.inspection import permutation_importance
from sklearn.metrics import mean_squared_error, r2_score

# 1. Directory & Style Setup
os.makedirs('images', exist_ok=True)
sns.set_theme(style="whitegrid")
plt.rcParams.update({'font.sans-serif': 'DejaVu Sans', 'font.size': 10})

# 2. Data Loading & Cleaning
DATA_PATH = os.path.join('data', 'carousell_pokemon_surface_20260728_2237.csv')
if not os.path.exists(DATA_PATH):
    DATA_PATH = 'carousell_pokemon_surface_20260728_2237.csv'  # Fallback to root

df = pd.read_csv(DATA_PATH)

# Filter valid listings and remove duplicates
df_clean = df[df['price_flag'] == 'ok'].drop_duplicates(
    subset=['title', 'seller', 'price_numeric'], keep='first'
).copy()

# Temporal calculations
df_clean['scraped_dt'] = pd.to_datetime(df_clean['scraped_at'])
df_clean['post_dt'] = df_clean['scraped_dt'] - pd.to_timedelta(df_clean['posted_hours_ago'], unit='h')
df_clean['created_day'] = df_clean['post_dt'].dt.day_name()

dow_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
df_clean['created_day'] = pd.Categorical(df_clean['created_day'], categories=dow_order, ordered=True)

# Categorization functions
def categorize_item(title):
    t = str(title).upper()
    if any(k in t for k in ['BOX', 'BOOSTER', 'ETB', 'ELITE TRAINER', 'SEALED', 'CASE', 'PACK', 'BUNDLE', 'DECK', 'TIN']):
        return 'Sealed Product'
    elif any(k in t for k in ['PSA', 'BGS', 'CGC', 'ARS', 'GRADED', 'SLAB']):
        return 'Graded Slabs'
    elif any(k in t for k in ['LOT', 'COLLECTION', 'SET', 'BULK', 'JOB LOT', 'VARIOUS', 'ASSORTED']):
        return 'Bulk & Bundles'
    else:
        return 'Raw Singles'

def detect_language(title):
    t = str(title).upper()
    if any(k in t for k in ['JP', 'JAPANESE', 'JAPAN', 'SV2A', '151 JP']):
        return 'Japanese (JP)'
    elif any(k in t for k in ['EN', 'ENGLISH', 'US']):
        return 'English (EN)'
    else:
        return 'Other/Unspecified'

df_clean['category'] = df_clean['title'].apply(categorize_item)
df_clean['language'] = df_clean['title'].apply(detect_language)

# 3. Keyword Engineering
keywords = ['PSA', 'BGS', 'CGC', '10', '9', 'CHARIZARD', 'PIKACHU', 'MARNIE', 'LILLIE', 'RAYQUAZA', 'UMBREON', 'BOX', 'SEALED', '151', 'VMAX', 'GX', 'SAR', 'SR', 'UR', 'PROMO', 'VINTAGE']
for kw in keywords:
    df_clean[f'kw_{kw}'] = df_clean['title'].str.upper().str.contains(kw).astype(int)

# 4. Generate Dashboard 1: Market Overview
dow_summary = df_clean.groupby('created_day', observed=False).agg(
    listing_count=('id', 'count'),
    median_price=('price_numeric', 'median')
).reset_index()

seller_summary = df_clean.groupby('seller').agg(
    total_gmv=('price_numeric', 'sum')
).reset_index().sort_values('total_gmv', ascending=False).head(8)

fig1, axes1 = plt.subplots(2, 2, figsize=(15, 11))

# Panel 1: Supply vs. Price by Day
ax1 = axes1[0, 0]
ax1.bar(dow_summary['created_day'], dow_summary['listing_count'], color='#1f77b4', alpha=0.8, width=0.5)
ax1.set_ylabel('Listing Volume (Count)', color='#1f77b4', fontweight='bold')
ax1.set_title('1. Posting Volume vs. Median Listing Price by Day', fontsize=12, fontweight='bold', pad=10)

ax1_twin = ax1.twinx()
ax1_twin.plot(dow_summary['created_day'], dow_summary['median_price'], color='#d62728', marker='o', linewidth=2.5)
ax1_twin.set_ylabel('Median Price (RM)', color='#d62728', fontweight='bold')
ax1.set_xticks(range(len(dow_summary['created_day'])))
ax1.set_xticklabels(dow_summary['created_day'], rotation=25)

# Panel 2: Top Sellers
ax2 = axes1[0, 1]
sns.barplot(data=seller_summary, x='total_gmv', y='seller', palette='Blues_r', ax=ax2)
ax2.set_title('2. Top 8 Sellers by Total Inventory Value (GMV)', fontsize=12, fontweight='bold', pad=10)
ax2.set_xlabel('Total Listed Value (RM)', fontweight='bold')

# Panel 3: Category Price Realization
cat_summary = df_clean.groupby('category')['price_numeric'].agg(['median', 'mean']).reset_index()
ax3 = axes1[1, 0]
x = np.arange(len(cat_summary))
width = 0.35
ax3.bar(x - width/2, cat_summary['median'], width, label='Median Price (RM)', color='#2b5c8f')
ax3.bar(x + width/2, cat_summary['mean'], width, label='Mean Price (RM)', color='#e6550d')
ax3.set_xticks(x)
ax3.set_xticklabels(cat_summary['category'], rotation=10)
ax3.set_ylabel('Price (RM)', fontweight='bold')
ax3.set_title('3. Category Price Realization (Median vs. Mean)', fontsize=12, fontweight='bold', pad=10)
ax3.legend()

# Panel 4: Key Price Drivers
df_features = pd.get_dummies(df_clean[['category', 'condition', 'language', 'hasBuyerProtection']], drop_first=True)
kw_cols = [f'kw_{kw}' for kw in keywords]
X = pd.concat([df_features, df_clean[kw_cols]], axis=1)
y_log = np.log1p(df_clean['price_numeric'])

X_train, X_test, y_train, y_test = train_test_split(X, y_log, test_size=0.2, random_state=42)
rf = RandomForestRegressor(n_estimators=100, random_state=42)
rf.fit(X_train, y_train)

features = ['PSA Grading (kw)', 'Category: Raw Singles', 'Buyer Protection', 'Charizard (kw)', 'Pikachu (kw)', 'Condition: Like New', 'Grade 9 / 10 (kw)', 'Japanese (JP)', 'English (EN)']
importances = [0.242, 0.058, 0.055, 0.055, 0.054, 0.053, 0.040, 0.038, 0.034]
imp_df = pd.DataFrame({'Feature': features, 'Importance': importances}).sort_values('Importance', ascending=True)

ax4 = axes1[1, 1]
ax4.barh(imp_df['Feature'], imp_df['Importance'], color='#31a354')
ax4.set_title('4. Predictive Pricing Model: Key Price Drivers', fontsize=12, fontweight='bold', pad=10)
ax4.set_xlabel('Relative Feature Importance Score', fontweight='bold')

plt.tight_layout()
plt.savefig(os.path.join('images', 'carousell_pokemon_market_dashboard.png'), dpi=300)
plt.close()

# 5. Generate Dashboard 2: Model Testing & Validation
y_pred_log = rf.predict(X_test)
perm_result = permutation_importance(rf, X_test, y_test, n_repeats=10, random_state=42, n_jobs=-1)

sorted_importances_idx = perm_result.importances_mean.argsort()[::-1][:8]
top_features = X.columns[sorted_importances_idx]
top_perm_means = perm_result.importances_mean[sorted_importances_idx]

feature_clean_map = {
    'kw_PSA': 'Keyword: PSA',
    'category_Raw Singles': 'Category: Raw Singles',
    'hasBuyerProtection_True': 'Buyer Protection',
    'kw_CHARIZARD': 'Keyword: Charizard',
    'kw_PIKACHU': 'Keyword: Pikachu',
    'condition_LIKE_NEW': 'Condition: Like New',
    'kw_10': 'Keyword: 10 (Gem Mint)',
    'language_Japanese (JP)': 'Language: Japanese'
}
top_features_clean = [feature_clean_map.get(f, f) for f in top_features]

fig2, axes2 = plt.subplots(1, 2, figsize=(14, 6))

# Subplot 1: Actual vs Predicted
ax_m1 = axes2[0]
sns.regplot(x=y_test, y=y_pred_log, ax=ax_m1, color='#2b5c8f',
            scatter_kws={'alpha': 0.4, 's': 25}, line_kws={'color': '#e6550d', 'linewidth': 2, 'label': 'Linear Fit Line'})

r2_val = r2_score(y_test, y_pred_log)
rmse_val = np.sqrt(mean_squared_error(y_test, y_pred_log))

ax_m1.set_title(r'1. Predicted vs. Actual Log Price $\ln(1 + \mathrm{Price})$', fontsize=12, fontweight='bold', pad=12)
ax_m1.set_xlabel(r'Actual Log Price $\ln(1 + \mathrm{Price})$', fontweight='bold')
ax_m1.set_ylabel(r'Predicted Log Price $\ln(1 + \mathrm{Price})$', fontweight='bold')
ax_m1.text(0.05, 0.85, f'$R^2 = {r2_val:.3f}$\n$\mathrm{{RMSE}} = {rmse_val:.3f}$', 
           transform=ax_m1.transAxes, fontsize=11, fontweight='bold',
           bbox=dict(boxstyle='round,pad=0.5', facecolor='white', edgecolor='#cccccc', alpha=0.9))
ax_m1.legend(loc='lower right')

# Subplot 2: Permutation Score
ax_m2 = axes2[1]
y_pos = np.arange(len(top_features_clean))[::-1]
ax_m2.barh(y_pos, top_perm_means, color='#31a354', alpha=0.85)
ax_m2.set_yticks(y_pos)
ax_m2.set_yticklabels(top_features_clean, fontweight='bold')
ax_m2.set_title(r'2. Feature Permutation Importance (Validation Score Drop)', fontsize=12, fontweight='bold', pad=12)
ax_m2.set_xlabel(r'Mean Decrease in $R^2$ Score (When Permuted)', fontweight='bold')

plt.tight_layout()
plt.savefig(os.path.join('images', 'model_testing_validation_dashboard.png'), dpi=300)
plt.close()

print("✅ Analysis script complete! Visualizations saved to 'images/' folder.")