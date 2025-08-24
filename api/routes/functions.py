import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from tqdm import tqdm
from collections import defaultdict
import re
try:
    from darts import TimeSeries
except ImportError:
    print("ERROR: Library Darts tidak terinstal. Jalankan: pip install darts")
    exit()

rules = pd.read_csv('./data/association_rules.csv')

rules['antecedents'] = rules['antecedents'].apply(lambda x: [i.strip() for i in str(x).split(",")])
rules['consequents'] = rules['consequents'].apply(lambda x: [i.strip() for i in str(x).split(",")])

def get_bundling(product: str, top_n: int = 1):
    recs = rules[rules['antecedents'].apply(lambda x: product in x)]
    recs = recs.sort_values(by="confidence", ascending=False)
    result = recs.head(top_n)[['antecedents', 'consequents', 'confidence', 'lift']]
    
    return result.to_dict(orient='records')

def load_historical_data(path="data/dataset_fix.csv", required_cols=('date','family','type','sales'),
                         fallback_days=7, random_seed=42):
    try:
        hist_raw = pd.read_csv(path)
        # parse date (tolerant)
        if 'date' in hist_raw.columns:
            hist_raw['date'] = pd.to_datetime(hist_raw['date'], errors='coerce')
        # if sales named differently, attempt rename
        if 'sales' not in hist_raw.columns and 'jumlah_terjual' in hist_raw.columns:
            hist_raw = hist_raw.rename(columns={'jumlah_terjual': 'sales'})

        # verify required cols present
        if set(required_cols).issubset(hist_raw.columns):
            # select & return copy with proper types
            historical_needed = hist_raw[list(required_cols)].copy()
            historical_needed['date'] = pd.to_datetime(historical_needed['date'])
            return historical_needed.reset_index(drop=True)
        else:
            raise ValueError("data/dataset_fix.csv not in expected format (missing required columns)")
    except Exception:
        # fallback dummy: last `fallback_days` days ending yesterday
        np.random.seed(random_seed)
        hist_dates = pd.to_datetime(pd.date_range(end=datetime.now().date() - timedelta(days=1), periods=fallback_days))
        # simple pattern: two families alternating (preserve original shape behavior)
        families = ['BEVERAGES', 'GROCERY I']
        types = ['D', 'C']
        repeats = len(hist_dates)
        historical_needed = pd.DataFrame({
            'date': np.repeat(hist_dates, len(families)),
            'family': families * repeats,
            'type': types * repeats,
            'sales': np.random.randint(50, 200, len(families) * repeats)
        })
        historical_needed['date'] = pd.to_datetime(historical_needed['date'])
        return historical_needed.reset_index(drop=True)

def normalize_product_name(name):
    if pd.isna(name):
        return ""
    s = str(name).lower()
    s = re.sub(r'[^a-z0-9]', '', s)
    return s

def input_int(prompt, default=None):
    s = input(prompt)
    if s.strip() == "" and default is not None:
        return default
    try:
        return int(s)
    except:
        print("Input tidak valid, coba lagi.")
        return input_int(prompt, default)

def load_and_preprocess_oil(path="data/oil.csv", start_date=None, end_date=None):
    try:
        df = pd.read_csv(path)
        # try common parse
        if 'date' in df.columns:
            try:
                df['date'] = pd.to_datetime(df['date'], format='%m/%d/%Y', errors='coerce')
            except:
                df['date'] = pd.to_datetime(df['date'], errors='coerce')
            price_col = [c for c in df.columns if c.lower() in ('price','oil','oil_price') or c.lower().startswith('price') ]
            if len(price_col) > 0:
                price_col = price_col[0]
            else:
                price_col = df.columns.difference(['date'])[0]
            df = df[['date', price_col]].rename(columns={price_col: 'oil_price'})
            df = df.dropna(subset=['date']).drop_duplicates(subset=['date']).set_index('date').sort_index()
            min_idx = df.index.min() if start_date is None else pd.to_datetime(start_date)
            max_idx = df.index.max() if end_date is None else pd.to_datetime(end_date)
            if pd.isna(min_idx) or pd.isna(max_idx):
                max_idx = pd.to_datetime(datetime.now().date())
                min_idx = max_idx - timedelta(days=30)
            full_idx = pd.date_range(start=min_idx, end=max_idx, freq='D')
            df = df.reindex(full_idx)
            df.index.name = 'date'
            df['oil_price'] = pd.to_numeric(df['oil_price'], errors='coerce')
            df['oil_price'] = df['oil_price'].interpolate(method='time').ffill().bfill()
        else:
            raise ValueError("no date column")
    except Exception:
        if start_date is None or end_date is None:
            end_idx = pd.to_datetime(datetime.now().date())
            start_idx = end_idx - timedelta(days=30)
        else:
            start_idx = pd.to_datetime(start_date)
            end_idx = pd.to_datetime(end_date)
        full_idx = pd.date_range(start=start_idx, end=end_idx, freq='D')
        df = pd.DataFrame(index=full_idx)
        df.index.name = 'date'
        df['oil_price'] = 0.0
    return df

def load_and_preprocess_holidays(path="data/Holiday Indonesian.csv", start_date=None, end_date=None):
    try:
        df = pd.read_csv(path)
        if 'date' not in df.columns:
            raise ValueError("no date")
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        if 'type_Additional' not in df.columns:
            df['type_Additional'] = 0
        if 'type_Holiday' not in df.columns:
            df['type_Holiday'] = 0
        df = df[['date','type_Additional','type_Holiday']].dropna(subset=['date']).drop_duplicates(subset=['date']).set_index('date').sort_index()
        min_idx = df.index.min() if start_date is None else pd.to_datetime(start_date)
        max_idx = df.index.max() if end_date is None else pd.to_datetime(end_date)
        if pd.isna(min_idx) or pd.isna(max_idx):
            max_idx = pd.to_datetime(datetime.now().date())
            min_idx = max_idx - timedelta(days=365)
        full_idx = pd.date_range(start=min_idx, end=max_idx, freq='D')
        df = df.reindex(full_idx)
        df.index.name = 'date'
        df['type_Additional'] = df['type_Additional'].fillna(0).astype(int)
        df['type_Holiday'] = df['type_Holiday'].fillna(0).astype(int)
    except Exception:
        if start_date is None or end_date is None:
            end_idx = pd.to_datetime(datetime.now().date())
            start_idx = end_idx - timedelta(days=365)
        else:
            start_idx = pd.to_datetime(start_date)
            end_idx = pd.to_datetime(end_date)
        full_idx = pd.date_range(start=start_idx, end=end_idx, freq='D')
        df = pd.DataFrame(index=full_idx)
        df.index.name = 'date'
        df['type_Additional'] = 0
        df['type_Holiday'] = 0
    return df

def build_covariates(oil_df, hol_df, start_date=None, end_date=None):
    if 'date' in oil_df.columns:
        oil_df = oil_df.set_index('date')
    if 'date' in hol_df.columns:
        hol_df = hol_df.set_index('date')
    merged = pd.merge(oil_df, hol_df, left_index=True, right_index=True, how='outer').sort_index()
    if start_date is None:
        start_date = merged.index.min()
    else:
        start_date = pd.to_datetime(start_date)
    if end_date is None:
        end_date = merged.index.max()
    else:
        end_date = pd.to_datetime(end_date)
    if pd.isna(start_date) or pd.isna(end_date):
        end_date = pd.to_datetime(datetime.now().date())
        start_date = end_date - timedelta(days=365)
    full_idx = pd.date_range(start=start_date, end=end_date, freq='D')
    merged = merged.reindex(full_idx)
    merged.index.name = 'date'
    merged['oil_price'] = pd.to_numeric(merged.get('oil_price'), errors='coerce')
    merged['oil_price'] = merged['oil_price'].interpolate(method='time').ffill().bfill()
    if 'type_Additional' not in merged.columns:
        merged['type_Additional'] = 0
    if 'type_Holiday' not in merged.columns:
        merged['type_Holiday'] = 0
    merged['type_Additional'] = merged['type_Additional'].fillna(0).astype(int)
    merged['type_Holiday'] = merged['type_Holiday'].fillna(0).astype(int)
    merged['is_holiday'] = merged['type_Holiday'].astype(int)
    merged['is_additional'] = merged['type_Additional'].astype(int)
    return merged[['oil_price','is_holiday','is_additional']].copy()

class Pipeline:
    def __init__(self):
        self.means = {}
    def transform(self, series, key=None):
        if not isinstance(series, pd.Series):
            series = pd.Series(series)
        mean = float(np.mean(series.values)) if len(series) > 0 else 1.0
        mean = mean if mean != 0 else 1.0
        self.means[key] = mean
        transformed = np.log1p(series.values / mean)
        return pd.Series(transformed, index=series.index)
    def inverse_transform(self, transformed_series, key=None):
        if not isinstance(transformed_series, pd.Series):
            transformed_series = pd.Series(transformed_series)
        mean = self.means.get(key, 1.0)
        inv = np.expm1(transformed_series.values) * mean
        return pd.Series(inv, index=transformed_series.index)

class Model:
    def __init__(self, beta_oil=0.02, beta_holiday=5.0, decay=0.98):
        self.beta_oil = float(beta_oil)
        self.beta_holiday = float(beta_holiday)
        self.decay = float(decay)
    def predict_one_step(self, ts_series, cov_df, next_date):
        if ts_series is None or len(ts_series) == 0:
            last_sales = 0.0
            last_date = None
        else:
            last_sales = float(ts_series.iloc[-1])
            last_date = ts_series.index[-1]
        if cov_df is None or cov_df.shape[0] == 0:
            last_oil = None
            future_oil = None
            future_hol = 0
        else:
            try:
                if last_date is not None and last_date in cov_df.index:
                    last_oil = float(cov_df.loc[last_date]['oil_price'])
                else:
                    last_oil = float(cov_df['oil_price'].iloc[-1])
            except:
                last_oil = float(cov_df['oil_price'].iloc[-1])
            try:
                if next_date in cov_df.index:
                    future_oil = float(cov_df.loc[next_date]['oil_price'])
                    future_hol = int(cov_df.loc[next_date].get('is_holiday', 0))
                else:
                    future_oil = float(cov_df['oil_price'].iloc[-1])
                    future_hol = int(cov_df['is_holiday'].iloc[-1]) if 'is_holiday' in cov_df.columns else 0
            except:
                future_oil = float(cov_df['oil_price'].iloc[-1])
                future_hol = int(cov_df['is_holiday'].iloc[-1]) if 'is_holiday' in cov_df.columns else 0
        base = last_sales * self.decay
        oil_effect = 0.0
        if (future_oil is not None) and (last_oil is not None):
            oil_effect = self.beta_oil * (future_oil - last_oil)
        hol_effect = float(self.beta_holiday * future_hol)
        pred = base + oil_effect + hol_effect
        pred = max(0.0, pred)
        return float(pred)

pipelines_dict = {
    "BEVERAGES": Pipeline(),
    "GROCERY I": Pipeline(),
    "BREAD/BAKERY": Pipeline()
}
models_dict = {
    "BEVERAGES": Model(beta_oil=0.03, beta_holiday=6.0),
    "GROCERY I": Model(beta_oil=0.01, beta_holiday=4.0),
    "BREAD/BAKERY": Model(beta_oil=0.00, beta_holiday=3.0)
}

product_to_category = {
    "Biskuat": "BREAD/BAKERY",
    "Beng Beng": "CELEBRATION",
    "Kwaci": "GROCERY I",
    "Indomie Goreng": "GROCERY I",
    "Indomie Kari Ayam": "GROCERY I",
    "Tango": "CELEBRATION",
    "Yupi": "CELEBRATION",
    "Sukro": "GROCERY I",
    "Momogi": "GROCERY I",
    "Taro": "GROCERY I",
    "Roma Kelapa": "BREAD/BAKERY",
    "Nabati Keju": "BREAD/BAKERY",
    "Mie Gemez": "GROCERY I",
    "Beras": "GROCERY I",
    "Big Babol": "CELEBRATION",
    "Good Day": "BEVERAGES",
    "Kapal Api": "BEVERAGES",
    "Torabika": "BEVERAGES",
    "Aqua": "BEVERAGES",
    "Pocari Sweat": "BEVERAGES",
    "Teh Kotak": "BEVERAGES",
    "Bimoli": "GROCERY II",
    "Sun Light Jeruk Nipis": "CLEANING",
    "Molto": "HOME CARE",
    "Pepsodent": "PERSONAL CARE",
    "Lifebuoy": "PERSONAL CARE",
    "Gula Pasir": "GROCERY I",
    "Pantene": "PERSONAL CARE",
    "Djarum": "LIQUOR,WINE,BEER"
}

# normalized product->family map
normalized_product_to_family = { normalize_product_name(k): v for k,v in product_to_category.items() }
# category->products fallback
category_to_products = defaultdict(list)
for p,c in product_to_category.items():
    category_to_products[c].append(p)
category_to_products = dict(category_to_products)

def extract_product_presence_store(raw_sales_df, product_map, warung_info):
    """
    Return store-level mapping:
      store_map[(family,type)][store_nbr][product] = recent_sales_sum
    """
    store_map = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    df = raw_sales_df.copy()
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'])
    if 'nama_produk' not in df.columns or 'store_nbr' not in df.columns:
        return store_map
    df['nama_produk_raw'] = df['nama_produk'].astype(str)
    df['nama_produk_norm'] = df['nama_produk_raw'].apply(normalize_product_name)
    df['family'] = df['nama_produk_norm'].map(product_map)
    df = pd.merge(df, warung_info, on='store_nbr', how='left')
    usable = df.dropna(subset=['family','type'])
    if usable.shape[0] == 0:
        return store_map
    if 'jumlah_terjual' in usable.columns:
        g = usable.groupby(['family','type','store_nbr','nama_produk_raw'])['jumlah_terjual'].sum().reset_index()
        for _, row in g.iterrows():
            fam = row['family']; t = row['type']; store = row['store_nbr']; prod = row['nama_produk_raw']; val = float(row['jumlah_terjual'])
            store_map[(fam,t)][store][prod] += val
    else:
        g = usable.groupby(['family','type','store_nbr','nama_produk_raw']).size().reset_index(name='cnt')
        for _, row in g.iterrows():
            fam = row['family']; t = row['type']; store = row['store_nbr']; prod = row['nama_produk_raw']; val = float(row['cnt'])
            store_map[(fam,t)][store][prod] += val
    return store_map

def map_and_agg_sales_by_type(daily_sales_df, product_map, warung_info):
    df = daily_sales_df.copy()
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'])
    df['nama_produk_raw'] = df['nama_produk'].astype(str)
    df['nama_produk_norm'] = df['nama_produk_raw'].apply(normalize_product_name)
    df['family'] = df['nama_produk_norm'].map(product_map)
    df = df.dropna(subset=['family'])
    df = pd.merge(df, warung_info, on='store_nbr', how='left')
    df = df.dropna(subset=['type'])
    agg_sales = df.groupby(['date','family','type'])['jumlah_terjual'].sum().reset_index().rename(columns={'jumlah_terjual':'sales'})
    return agg_sales

def load_historical_data(path="data/dataset_fix.csv", required_cols=('date','family','type','sales'),
                         fallback_days=7, random_seed=42):
    try:
        hist_raw = pd.read_csv(path)
        # parse date (tolerant)
        if 'date' in hist_raw.columns:
            hist_raw['date'] = pd.to_datetime(hist_raw['date'], errors='coerce')
        # if sales named differently, attempt rename
        if 'sales' not in hist_raw.columns and 'jumlah_terjual' in hist_raw.columns:
            hist_raw = hist_raw.rename(columns={'jumlah_terjual': 'sales'})

        # verify required cols present
        if set(required_cols).issubset(hist_raw.columns):
            # select & return copy with proper types
            historical_needed = hist_raw[list(required_cols)].copy()
            historical_needed['date'] = pd.to_datetime(historical_needed['date'])
            return historical_needed.reset_index(drop=True)
        else:
            raise ValueError("data/dataset_fix.csv not in expected format (missing required columns)")
    except Exception:
        # fallback dummy: last `fallback_days` days ending yesterday
        np.random.seed(random_seed)
        hist_dates = pd.to_datetime(pd.date_range(end=datetime.now().date() - timedelta(days=1), periods=fallback_days))
        # simple pattern: two families alternating (preserve original shape behavior)
        families = ['BEVERAGES', 'GROCERY I']
        types = ['D', 'C']
        repeats = len(hist_dates)
        historical_needed = pd.DataFrame({
            'date': np.repeat(hist_dates, len(families)),
            'family': families * repeats,
            'type': types * repeats,
            'sales': np.random.randint(50, 200, len(families) * repeats)
        })
        historical_needed['date'] = pd.to_datetime(historical_needed['date'])
        return historical_needed.reset_index(drop=True)

def run_prediction_and_return_product_list(laporan_harian, warung_info,
                                           oil_path="data/oil.csv", holiday_path="data/Holiday Indonesian.csv",
                                           prediction_horizon_days=1):
    # ensure date types
    historical = hist_df.copy()
    historical['date'] = pd.to_datetime(historical['date'])
    laporan = laporan_harian.copy()
    laporan['date'] = pd.to_datetime(laporan['date'])

    # covariates
    min_date = min(historical['date'].min(), laporan['date'].min())
    max_date = max(historical['date'].max(), laporan['date'].max()) + timedelta(days=prediction_horizon_days + 3)
    oil_df = load_and_preprocess_oil(oil_path, start_date=min_date, end_date=max_date)
    hol_df = load_and_preprocess_holidays(holiday_path, start_date=min_date, end_date=max_date)
    cov_df = build_covariates(oil_df, hol_df, start_date=min_date, end_date=max_date)

    # product presence per store extracted from laporan (single-record default)
    store_prod_map = extract_product_presence_store(laporan, normalized_product_to_family, warung_info)

    # aggregate incoming laporan to family-level
    sales_today_agg = map_and_agg_sales_by_type(laporan, normalized_product_to_family, warung_info)

    # combine with historical (historical assumed to be family-level with columns date,family,type,sales)
    updated_raw = pd.concat([historical, sales_today_agg], ignore_index=True)
    if 'jumlah_terjual' in updated_raw.columns and 'sales' not in updated_raw.columns:
        updated_raw = updated_raw.rename(columns={'jumlah_terjual':'sales'})
    updated = updated_raw.groupby(['date','family','type'])['sales'].sum().reset_index()
    updated['date'] = pd.to_datetime(updated['date'])

    # predict family-level
    family_preds = []
    for fam in updated['family'].unique():
        if fam not in models_dict:
            continue
        model = models_dict[fam]
        pipeline = pipelines_dict.get(fam, None)
        df_fam = updated[updated['family'] == fam].sort_values('date')
        for t in df_fam['type'].unique():
            df_t = df_fam[df_fam['type'] == t]
            if df_t.shape[0] == 0:
                sample_date = pd.to_datetime(laporan['date'].min())
                series_df = pd.DataFrame({'sales': [0]}, index=[sample_date])
            else:
                start = df_t['date'].min()
                end = df_t['date'].max()
                full_idx = pd.date_range(start=start, end=end, freq='D')
                tmp = df_t.set_index('date').reindex(full_idx).fillna(0)
                series_df = tmp[['sales']].copy() if 'sales' in tmp.columns else tmp.iloc[:, [0]].rename(columns={tmp.columns[0]:'sales'})
            series_df.index.name = 'date'
            sales_series = series_df['sales']
            if pipeline is not None:
                try:
                    pipeline.transform(sales_series, key=f"{fam}__{t}")
                except:
                    pass
            last_idx = sales_series.index[-1]
            next_dates = [last_idx + timedelta(days=d) for d in range(1, prediction_horizon_days + 1)]
            for nd in next_dates:
                pred_val = model.predict_one_step(sales_series, cov_df, nd)
                family_preds.append({'date': nd.strftime('%Y-%m-%d'), 'family': fam, 'type': t, 'predicted_sales': float(round(pred_val,2))})

    if len(family_preds) == 0:
        return []

    preds_family_df = pd.DataFrame(family_preds)

    # Allocate family preds to store->product using store_prod_map (preferred).
    # Then aggregate per product across all input stores and return only product + predicted_sales
    product_alloc = defaultdict(float)  # product -> aggregated predicted sales

    input_stores = set(warung_info['store_nbr'].tolist())

    for _, row in preds_family_df.iterrows():
        fam = row['family']; t = row['type']; pred_sales = float(row['predicted_sales'])
        key = (fam, t)
        store_dict = store_prod_map.get(key, {})  # store -> {product: val}

        if len(store_dict) > 0:
            # compute total recent sales per store for this (fam,type)
            store_totals = {s: sum(prods.values()) for s, prods in store_dict.items()}
            total_all = sum(store_totals.values())
            if total_all == 0:
                # equal split among stores
                stores_list = list(store_dict.keys())
                if len(stores_list) == 0:
                    # fallback to category representatives
                    reps = category_to_products.get(fam, [])
                    if len(reps) == 0:
                        product_alloc[f"UNKNOWN_PRODUCT_{fam}_{t}"] += pred_sales
                    else:
                        product_alloc[reps[0]] += pred_sales
                    continue
                alloc_per_store = pred_sales / len(stores_list)
                for s in stores_list:
                    prods = store_dict[s]
                    if len(prods) == 0:
                        continue
                    total_p = sum(prods.values())
                    if total_p > 0:
                        for prod, v in prods.items():
                            share = alloc_per_store * (v / total_p)
                            # only include stores that were input by user
                            if s in input_stores:
                                product_alloc[prod] += share
                    else:
                        each = alloc_per_store / max(1, len(prods))
                        for prod in prods.keys():
                            if s in input_stores:
                                product_alloc[prod] += each
            else:
                # allocate pred_sales to stores proportionally by store_totals
                for s, st_total in store_totals.items():
                    store_alloc = pred_sales * (st_total / total_all)
                    prods = store_dict[s]
                    total_p = sum(prods.values())
                    if total_p > 0:
                        for prod, v in prods.items():
                            share = store_alloc * (v / total_p)
                            if s in input_stores:
                                product_alloc[prod] += share
                    else:
                        each = store_alloc / max(1, len(prods))
                        for prod in prods.keys():
                            if s in input_stores:
                                product_alloc[prod] += each
            continue

        # fallback: no store-level product info for this family-type
        reps = category_to_products.get(fam, [])
        if len(reps) == 0:
            product_alloc[f"UNKNOWN_PRODUCT_{fam}_{t}"] += pred_sales
        else:
            product_alloc[reps[0]] += pred_sales

    # Build output list as requested: only product + predicted_sales (rounded)
    output_list = []
    for prod, val in product_alloc.items():
        output_list.append({'product': prod, 'predicted_sales': float(round(val, 2))})

    return output_list

hist_df = load_historical_data("data/dataset_fix.csv", fallback_days=7)
last_historical_date = hist_df['date'].max()
today_simulation = last_historical_date + timedelta(days=1)

# try:
#         historical_data_raw = pd.read_csv("dataset_fix.csv")
#         historical_data_raw['date'] = pd.to_datetime(historical_data_raw['date'])
#         # Pilih hanya kolom yang relevan
#         historical_data = historical_data_raw[['date', 'family', 'type', 'sales']]
#         print("✅ Data historis 'dataset_fix.csv' berhasil dimuat.")
# except FileNotFoundError:
#         print("\nPERINGATAN: File 'dataset_fix.csv' tidak ditemukan. Menggunakan data historis dummy.")
#         # Jika file tidak ada, buat data historis dummy
#         historical_dates = pd.to_datetime(pd.date_range(end=datetime.now().date() - timedelta(days=1), periods=30))
#         historical_data = pd.DataFrame({
#             'date': np.repeat(historical_dates, 4), 'family': ['BEVERAGES', 'GROCERY I'] * 60,
#             'type': ['C', 'D', 'C', 'D'] * 30, 'sales': np.random.randint(50, 200, 120)
#         })