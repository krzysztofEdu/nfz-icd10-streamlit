import io
import time
import requests
import pandas as pd
import streamlit as st

# ----------------------------------------------------
# KONFIGURACJA STRONY I STYL
# ----------------------------------------------------
st.set_page_config(
    page_title="NFZ ICD-10 Explorer",
    page_icon="📊",
    layout="wide"
)

# Delikatny custom CSS: szeroka strona, karty, ładniejsze przyciski itd.
st.markdown("""
    <style>
        .block-container {
            padding-top: 1rem;
            padding-bottom: 1rem;
            padding-left: 2rem;
            padding-right: 2rem;
            max-width: 95%;
        }
        h1, h2, h3 {
            font-family: 'Segoe UI', sans-serif;
            font-weight: 600;
        }
        .stButton>button {
            width: 100%;
            border-radius: 0.6rem;
            height: 3rem;
            font-size: 1.05rem;
        }
        .card {
            padding: 1rem 1.2rem;
            border-radius: 0.8rem;
            border: 1px solid #e5e7eb;
            background-color: #f9fafb;
            box-shadow: 0 1px 3px rgba(15,23,42,0.08);
            margin-bottom: 1rem;
        }
        .card h3 {
            margin-top: 0;
            margin-bottom: 0.4rem;
            font-size: 1.05rem;
        }
        .small-label {
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: #6b7280;
        }
        .filter-banner {
            padding: 0.6rem 0.9rem;
            border-radius: 0.5rem;
            border: 1px solid #d1d5db;
            background-color: #f3f4f6;
            font-size: 0.9rem;
            margin-bottom: 0.6rem;
        }
        .filter-badge {
            display: inline-block;
            padding: 0.1rem 0.4rem;
            margin-right: 0.4rem;
            border-radius: 999px;
            background-color: #e5e7eb;
            font-size: 0.8rem;
        }
    </style>
""", unsafe_allow_html=True)


# ----------------------------------------------------
# CALLBACK: czyszczenie filtrów
# ----------------------------------------------------
def clear_filters():
    # czyścimy pola inputów
    st.session_state["filt_code_input"] = ""
    st.session_state["filt_name_input"] = ""
    # czyścimy też wartości zastosowanych filtrów
    st.session_state["filt_code_applied"] = ""
    st.session_state["filt_name_applied"] = ""


# ----------------------------------------------------
# FUNKCJA: pobieranie danych z NFZ (z paskami postępu) + CACHE
# ----------------------------------------------------
@st.cache_data(show_spinner=False)
def pobierz_icd10_nfz(szuk, rok=2019, limit=25):
    """
    Pobiera benefity NFZ → tabele → dane ICD-10.
    Zwraca:
      - df_allICD  (bez duplikatów)
      - df_errors  (lista błędów w jednej tabeli)
    Używa cache (st.cache_data) – dla tych samych parametrów wynik jest buforowany.
    """

    pd.set_option("display.max_colwidth", 100)

    lista_bledow = []
    lista_df = []
    lista_dfICD = []
    df_all = pd.DataFrame()
    df_allICD = pd.DataFrame()

    # 1️⃣ Pobranie listy benefitów
    try:
        url = (
            "https://api.nfz.gov.pl/app-stat-api-jgp/benefits"
            f"?benefit={szuk}&catalog=1a&page=1&limit={limit}&api-version=1.1"
        )
        resp = requests.get(url)
        resp.raise_for_status()
        js = resp.json()

        # sprawdzamy, czy w ogóle jest "data"
        if "data" not in js:
            df_err = pd.DataFrame([{
                "etap": "benefits",
                "kod/ID": None,
                "komunikat": f"Brak klucza 'data' w odpowiedzi API. Otrzymano klucze: {list(js.keys())}"
            }])
            return pd.DataFrame(), df_err

        df_wysz = pd.DataFrame(js["data"])

        # sprawdzamy, czy coś przyszło
        if df_wysz.empty:
            df_err = pd.DataFrame([{
                "etap": "benefits",
                "kod/ID": None,
                "komunikat": f"Brak wyników dla parametru benefit='{szuk}'."
            }])
            return pd.DataFrame(), df_err

        # sprawdzamy, czy jest kolumna 'code'
        if "code" not in df_wysz.columns:
            df_err = pd.DataFrame([{
                "etap": "benefits",
                "kod/ID": None,
                "komunikat": f"Brak kolumny 'code' w odpowiedzi API. Dostępne kolumny: {list(df_wysz.columns)}"
            }])
            return pd.DataFrame(), df_err

    except Exception as e:
        df_err = pd.DataFrame([{
            "etap": "benefits",
            "kod/ID": None,
            "komunikat": str(e)
        }])
        return pd.DataFrame(), df_err

    # 2️⃣ Pobieranie tabel index-of-tables z paskiem postępu
    codes = list(df_wysz["code"])
    total_codes = len(codes)
    progress_tables = st.progress(0, text="Pobieranie tabel index-of-tables...")

    for i, kod in enumerate(codes, start=1):
        try:
            url_kod = (
                "https://api.nfz.gov.pl/app-stat-api-jgp/index-of-tables"
                f"?catalog=1a&name={kod}&year={rok}&format=json&api-version=1.1"
            )
            r = requests.get(url_kod)
            r.raise_for_status()
            js_p = r.json()

            if "data" not in js_p:
                lista_bledow.append({
                    "etap": "index-of-tables",
                    "kod/ID": kod,
                    "komunikat": f"Brak klucza 'data' w odpowiedzi API (index-of-tables). Klucze: {list(js_p.keys())}"
                })
                continue

            tables = js_p["data"]["attributes"]["years"][0]["tables"]
            df_kod = pd.DataFrame(tables)

            # usuń zbędne kolumny
            for col in ["attributes", "links"]:
                if col in df_kod.columns:
                    df_kod = df_kod.drop(columns=[col])

            df_kod["code"] = kod
            lista_df.append(df_kod)
            df_all = pd.concat(lista_df, ignore_index=True)

        except Exception as e:
            lista_bledow.append({
                "etap": "index-of-tables",
                "kod/ID": kod,
                "komunikat": str(e)
            })

        progress_tables.progress(
            i / total_codes,
            text=f"Pobieranie tabel index-of-tables... ({i}/{total_codes})"
        )

    # jeśli nic nie pobrano – kończymy
    if df_all.empty:
        progress_tables.empty()
        df_errors = pd.DataFrame(lista_bledow) if lista_bledow else pd.DataFrame(
            columns=["etap", "kod/ID", "komunikat"]
        )
        return pd.DataFrame(), df_errors

    progress_tables.empty()

    # 3️⃣ Pobieranie ICD-10 z paskiem postępu
    url_icd = "https://api.nfz.gov.pl/app-stat-api-jgp/icd10-diseases/"

    if "type" not in df_all.columns:
        lista_bledow.append({
            "etap": "index-of-tables",
            "kod/ID": None,
            "komunikat": f"Brak kolumny 'type' w df_all. Dostępne kolumny: {list(df_all.columns)}"
        })
        df_errors = pd.DataFrame(lista_bledow)
        return pd.DataFrame(), df_errors

    df_linkICD = df_all[df_all["type"] == "icd-10-diseases"]

    total_icd = len(df_linkICD)
    progress_icd = st.progress(0, text="Pobieranie danych ICD-10...")

    for j, (_, row) in enumerate(df_linkICD.iterrows(), start=1):
        try:
            id_value = row["id"]
            link_final = (
                f"{url_icd}{id_value}"
                "?page=1&limit=25&format=json&api-version=1.1"
            )

            r = requests.get(link_final)
            r.raise_for_status()
            js_i = r.json()

            if "data" not in js_i:
                lista_bledow.append({
                    "etap": "icd10-diseases",
                    "kod/ID": id_value,
                    "komunikat": f"Brak klucza 'data' w odpowiedzi API (icd10-diseases). Klucze: {list(js_i.keys())}"
                })
                continue

            df_icd = pd.DataFrame(js_i["data"]["attributes"]["data"])

            # dodaj kod benefitu
            df_icd["benefit-code"] = row["code"]

            # usuń ewentualne kolumny typu table-id
            for col in ["table-id", "table_id", "tableid"]:
                if col in df_icd.columns:
                    df_icd = df_icd.drop(columns=[col])

            lista_dfICD.append(df_icd)
            df_allICD = pd.concat(lista_dfICD, ignore_index=True)

        except Exception as e:
            lista_bledow.append({
                "etap": "icd10-diseases",
                "kod/ID": id_value,
                "komunikat": str(e)
            })

        if total_icd > 0:
            progress_icd.progress(
                j / total_icd,
                text=f"Pobieranie danych ICD-10... ({j}/{total_icd})"
            )

    progress_icd.empty()

    # 4️⃣ Usuwanie duplikatów i sortowanie
    if not df_allICD.empty:
        df_allICD = df_allICD.drop_duplicates().reset_index(drop=True)
        if "disease-code" in df_allICD.columns:
            df_allICD = df_allICD.sort_values(by="disease-code").reset_index(drop=True)

    # 5️⃣ Podsumowanie błędów
    df_errors = pd.DataFrame(lista_bledow) if lista_bledow else \
        pd.DataFrame(columns=["etap", "kod/ID", "komunikat"])

    return df_allICD, df_errors


# ----------------------------------------------------
# APLIKACJA STREAMLIT
# ----------------------------------------------------
def main():
    # ------------------- SIDEBAR -------------------
    st.sidebar.title("⚙️ Ustawienia zapytania")

    szuk = st.sidebar.text_input(
        "Fragment nazwy świadczenia (benefit):",
        value="rozrodcz",
        placeholder="np. rozrodcz, poród, kardio…",
        help="Wpisz fragment nazwy świadczenia, np. 'rozrodcz', 'poród', 'kardio'."
    )

    rok = st.sidebar.number_input(
        "Rok tabel NFZ:",
        min_value=2010,
        max_value=2030,
        value=2019,
        step=1
    )

    limit = st.sidebar.number_input(
        "Limit wyników (lista świadczeń):",
        min_value=1,
        max_value=200,
        value=25,
        step=1
    )

    st.sidebar.markdown("---")
    uruchom = st.sidebar.button("🚀 Pobierz dane z NFZ")

    # Utrzymanie wyników i czasu w session_state
    if "df_icd" not in st.session_state:
        st.session_state["df_icd"] = pd.DataFrame()
    if "df_errors" not in st.session_state:
        st.session_state["df_errors"] = pd.DataFrame()
    if "last_runtime" not in st.session_state:
        st.session_state["last_runtime"] = None

    # ------------------- POBIERANIE DANYCH -------------------
    if uruchom:
        if not szuk:
            st.sidebar.warning("Wpisz proszę jakiś fragment nazwy świadczenia.")
        else:
            with st.status("⏳ Rozpoczynam pobieranie danych z NFZ...", expanded=True) as status:
                start_time = time.perf_counter()

                st.write("🔍 Krok 1/3 — Pobieranie listy świadczeń (benefits) oraz tabel...")
                df_icd, df_errors = pobierz_icd10_nfz(
                    szuk=szuk,
                    rok=int(rok),
                    limit=int(limit)
                )

                elapsed = time.perf_counter() - start_time

                st.write("📊 Krok 2/3 — Przetwarzanie danych i aktualizacja interfejsu...")
                st.session_state["df_icd"] = df_icd
                st.session_state["df_errors"] = df_errors
                st.session_state["last_runtime"] = elapsed

                st.write("✅ Krok 3/3 — Zakończono pobieranie danych.")

                status.update(
                    label=f"✅ Gotowe! Dane poprawnie pobrano z NFZ w około {elapsed:.1f} s.",
                    state="complete",
                    expanded=False,
                )

    # *** Po ewentualnym pobraniu zawsze korzystamy z session_state ***
    df_icd = st.session_state["df_icd"]
    df_errors = st.session_state["df_errors"]
    last_runtime = st.session_state["last_runtime"]

    # ------------------- GŁÓWNY NAGŁÓWEK -------------------
    st.title("📊 NFZ ICD-10 Explorer")
    st.markdown(
        "Interaktywne pobieranie i filtrowanie kodów **ICD-10** "
        "powiązanych ze świadczeniami z katalogu **NFZ (JGP)**."
    )

    # Karty podsumowujące
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.markdown(
            '<div class="card"><div class="small-label">Aktualny parametr</div>'
            f'<h3>benefit = \"{szuk}\"</h3></div>',
            unsafe_allow_html=True
        )
    with col_b:
        st.markdown(
            '<div class="card"><div class="small-label">Rok</div>'
            f'<h3>{int(rok)}</h3></div>',
            unsafe_allow_html=True
        )
    with col_c:
        n_rek = len(df_icd) if not df_icd.empty else 0
        st.markdown(
            '<div class="card"><div class="small-label">Liczba rekordów ICD-10</div>'
            f'<h3>{n_rek}</h3></div>',
            unsafe_allow_html=True
        )

    # Zakładki
    tab_wyniki, tab_bledy, tab_ust = st.tabs(
        ["📊 Wyniki ICD-10", "⚠️ Błędy", "ℹ️ Info / Parametry"]
    )

    # --------- ZAKŁADKA: WYNIKI ---------
    with tab_wyniki:
        st.header("Wyniki ICD-10")

        if df_icd.empty:
            st.info("Brak danych ICD-10 (uruchom zapytanie w panelu bocznym).")
        else:
            # ---------------- FILTRY ----------------
            st.markdown("### Filtry")

            # inicjalizacja zastosowanych filtrów w session_state
            if "filt_code_applied" not in st.session_state:
                st.session_state["filt_code_applied"] = ""
            if "filt_name_applied" not in st.session_state:
                st.session_state["filt_name_applied"] = ""

            col1, col2, col3 = st.columns([1, 1, 1])

            with col1:
                filt_code = st.text_input(
                    "Filtr po disease-code (zawiera):",
                    key="filt_code_input",
                    placeholder="np. O80, C18…",
                )

            with col2:
                filt_name = st.text_input(
                    "Filtr po disease-name (zawiera):",
                    key="filt_name_input",
                    placeholder="np. poród, nowotwór…",
                )

            with col3:
                st.write("")
                st.write("")
                if st.button("✅ Zastosuj filtry"):
                    st.session_state["filt_code_applied"] = st.session_state.get("filt_code_input", "")
                    st.session_state["filt_name_applied"] = st.session_state.get("filt_name_input", "")
                st.button("🧹 Wyczyść filtry", on_click=clear_filters)

            # ---------------- ZASTOSOWANIE FILTRÓW ----------------
            df_filtr = df_icd.copy()

            code_filter = st.session_state.get("filt_code_applied", "")
            name_filter = st.session_state.get("filt_name_applied", "")

            if code_filter and "disease-code" in df_filtr.columns:
                df_filtr = df_filtr[
                    df_filtr["disease-code"]
                    .astype(str)
                    .str.contains(code_filter, case=False, na=False)
                ]

            if name_filter and "disease-name" in df_filtr.columns:
                df_filtr = df_filtr[
                    df_filtr["disease-name"]
                    .astype(str)
                    .str.contains(name_filter, case=False, na=False)
                ]

            # ---------------- BANEREK Z AKTYWNYMI FILTRAMI ----------------
            if code_filter or name_filter:
                badges = []
                if code_filter:
                    badges.append(f'<span class="filter-badge">disease-code zawiera: <b>{code_filter}</b></span>')
                if name_filter:
                    badges.append(f'<span class="filter-badge">disease-name zawiera: <b>{name_filter}</b></span>')
                badges_html = " ".join(badges)
                st.markdown(
                    f'<div class="filter-banner">'
                    f'<b>Aktywne filtry:</b> {badges_html}'
                    f'</div>',
                    unsafe_allow_html=True
                )
            else:
                st.markdown(
                    '<div class="filter-banner"><b>Aktywne filtry:</b> brak – wyświetlane są wszystkie rekordy.</div>',
                    unsafe_allow_html=True
                )

            st.write(
                f"Liczba unikalnych rekordów ICD-10 (po filtrach): **{len(df_filtr)}**"
            )
            st.dataframe(df_filtr, use_container_width=True)

            # ---------------- WYKRESY (SUMY) ----------------
            st.markdown("### Wykresy")

            # wybór miary do sumowania
            numeric_cols = df_filtr.select_dtypes(include="number").columns.tolist()

            if numeric_cols:
                # zapamiętaj ostatnio wybraną miarę
                if "chart_metric" not in st.session_state or st.session_state["chart_metric"] not in numeric_cols:
                    st.session_state["chart_metric"] = numeric_cols[0]

                metric = st.selectbox(
                    "Wybierz miarę do zsumowania na wykresach:",
                    options=numeric_cols,
                    index=numeric_cols.index(st.session_state["chart_metric"]),
                    help="Wykresy pokażą sumę wybranej miary dla kodów ICD-10 oraz świadczeń (benefit-code)."
                )
                st.session_state["chart_metric"] = metric

                col_chart1, col_chart2 = st.columns(2)

                # Wykres 1: suma miary po disease-code
                with col_chart1:
                    if "disease-code" in df_filtr.columns:
                        st.subheader(f"Top kody ICD-10 (suma: {metric})")
                        top_codes = (
                            df_filtr.groupby("disease-code")[metric]
                            .sum()
                            .sort_values(ascending=True)
                            .tail(20)
                        )
                        if not top_codes.empty:
                            st.bar_chart(top_codes)
                        else:
                            st.caption("Brak danych do wyświetlenia.")
                    else:
                        st.caption("Brak kolumny 'disease-code' w danych.")

                # Wykres 2: suma miary po benefit-code
                with col_chart2:
                    if "benefit-code" in df_filtr.columns:
                        st.subheader(f"Suma {metric} wg świadczeń (benefit-code)")
                        top_benefits = (
                            df_filtr.groupby("benefit-code")[metric]
                            .sum()
                            .sort_values(ascending=True)
                            .tail(20)
                        )
                        if not top_benefits.empty:
                            st.bar_chart(top_benefits)
                        else:
                            st.caption("Brak danych do wyświetlenia.")
                    else:
                        st.subheader("Rozkład wg świadczeń")
                        st.caption("Brak kolumny 'benefit-code' w danych.")
            else:
                st.info(
                    "Brak kolumn numerycznych w danych – nie można zbudować wykresów sum. "
                    "Sprawdź strukturę danych z NFZ."
                )

            # ---- POBIERANIE CSV / EXCEL ----
            st.markdown("### Pobierz wyniki")

            # CSV
            csv_bytes = df_filtr.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="📥 Pobierz jako CSV",
                data=csv_bytes,
                file_name=f"icd10_{szuk}_{rok}.csv",
                mime="text/csv",
            )

            # Excel – uniwersalne podejście z fallbackiem
            buffer = io.BytesIO()
            excel_engines = ["xlsxwriter", "openpyxl"]
            engine_used = None

            for eng in excel_engines:
                try:
                    buffer = io.BytesIO()
                    with pd.ExcelWriter(buffer, engine=eng) as writer:
                        df_filtr.to_excel(writer, index=False, sheet_name="ICD10")
                    engine_used = eng
                    break
                except Exception:
                    engine_used = None
                    continue

            if engine_used is None:
                st.warning(
                    "⚠️ Brak dostępnego silnika Excel (`xlsxwriter` / `openpyxl`). "
                    "Dostępny jest tylko eksport do CSV."
                )
            else:
                st.info(f"📘 Excel zapisany przy użyciu silnika: **{engine_used}**")
                buffer.seek(0)
                st.download_button(
                    label="📥 Pobierz jako Excel",
                    data=buffer,
                    file_name=f"icd10_{szuk}_{rok}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

    # --------- ZAKŁADKA: BŁĘDY ---------
    with tab_bledy:
        st.header("Błędy podczas pobierania")

        if df_errors.empty:
            st.success("Brak błędów (albo jeszcze nie uruchomiono zapytania).")
        else:
            st.dataframe(df_errors, use_container_width=True)

            csv_err = df_errors.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="📥 Pobierz listę błędów (CSV)",
                data=csv_err,
                file_name=f"errors_{szuk}_{rok}.csv",
                mime="text/csv",
            )

    # --------- ZAKŁADKA: INFO / PARAMETRY ---------
    with tab_ust:
        st.header("Informacje / Parametry zapytania")

        st.markdown("#### Aktualne parametry")
        st.json({
            "szuk (benefit)": szuk,
            "rok": int(rok),
            "limit (benefits)": int(limit),
        })

        st.markdown("---")
        st.markdown("#### Informacje o czasie pobierania")
        if last_runtime is not None:
            st.write(f"Ostatnie pobieranie danych NFZ trwało około **{last_runtime:.1f} s**.")
        else:
            st.write("Dane jeszcze nie były pobierane w tej sesji.")

        st.markdown("---")
        st.markdown("#### Ogólne informacje")
        st.write(
            "Aplikacja wysyła zapytania do API NFZ (JGP). "
            "Przy większej liczbie świadczeń pobieranie może potrwać kilka–kilkanaście sekund. "
            "Cache skraca czas kolejnych pobrań dla tych samych parametrów, "
            "a paski postępu pokazują tylko pierwsze, „prawdziwe” pobranie."
        )


if __name__ == "__main__":
    main()
