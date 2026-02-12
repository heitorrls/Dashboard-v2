import pandas as pd
import os
import unicodedata
import math
import time
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.types import String, Integer, Date, Text
from concurrent.futures import ProcessPoolExecutor

# --- CONFIGURAÇÃO ---
DB_URL = 'mysql+pymysql://root:Jjjb3509@127.0.0.1:3306/db_pnatrans'

try:
    engine_principal = create_engine(DB_URL, pool_pre_ping=True)
except Exception as e:
    print(f"Erro BD: {e}")

# --- WORKER PARA SALVAMENTO PARALELO ---
def worker_salvar_chunk(dados_chunk):
    if dados_chunk.empty: return
    try:
        engine_worker = create_engine(DB_URL, pool_pre_ping=True)
        with engine_worker.connect() as conn:
            dados_chunk.to_sql('capacitacoes', con=conn, if_exists='append', index=False, chunksize=1000)
    except Exception as e:
        print(f"  [Erro Worker] {e}")

# --- LIMPEZA E AUXILIARES ---
def limpar_data(valor):
    """Converte datas do Excel para YYYY-MM-DD"""
    try:
        if pd.isna(valor): return None
        if isinstance(valor, (pd.Timestamp, datetime)):
            return valor.date()
        # Tenta converter string BR 'dd/mm/yyyy'
        return pd.to_datetime(valor, dayfirst=True, errors='coerce').date()
    except:
        return None

def limpar_inteiro(valor):
    """Remove pontos e converte para int"""
    try:
        return int(float(str(valor).replace('.', '').replace(',', '.')))
    except:
        return 0

# --- PROCESSAMENTO ---
def processar_capacitacoes(PLANILHAS):
    nome_arquivo = 'Capacitação Relatório.xlsx'
    caminho = os.path.join(PLANILHAS, nome_arquivo)
    
    print(f"\n--- PROCESSANDO ARQUIVO: {nome_arquivo} ---")
    
    if not os.path.exists(caminho):
        print(f"  ❌ Erro: Arquivo não encontrado em {caminho}")
        return pd.DataFrame()

    try:
        # Lê o Excel (Assume que está na primeira aba)
        df = pd.read_excel(caminho, sheet_name=0)
        
        # Remove linhas totalmente vazias
        df = df.dropna(how='all')
        
        # Mapa de Colunas (Excel -> Banco)
        mapa_colunas = {
            'Ordem': 'ORDEM',
            'Data': 'DATA_CAPACITACAO',
            'DESCRIÇÃO DA CAPACITAÇÃO': 'DESCRICAO',
            'Lista de Presença': 'LISTA_PRESENCA',
            'Quantidade de Participantes': 'QTD_PARTICIPANTES',
            'Tipo': 'TIPO'
        }
        
        # Normaliza nomes das colunas do Excel
        df.columns = [str(c).strip().replace('\n', ' ') for c in df.columns]
        
        # Renomeia
        df.rename(columns=mapa_colunas, inplace=True)
        
        # Garante que só temos as colunas mapeadas e existentes
        cols_finais = [c for c in mapa_colunas.values() if c in df.columns]
        df = df[cols_finais]

        # --- TRATAMENTO DE DADOS ---
        
        # 1. Data
        if 'DATA_CAPACITACAO' in df.columns:
            df['DATA_CAPACITACAO'] = df['DATA_CAPACITACAO'].apply(limpar_data)
            df = df.dropna(subset=['DATA_CAPACITACAO'])

        # 2. Inteiros
        for col in ['ORDEM', 'QTD_PARTICIPANTES']:
            if col in df.columns:
                df[col] = df[col].apply(limpar_inteiro)

        # 3. Textos (Preenche vazios) - CORREÇÃO AQUI (.str.strip)
        cols_txt = ['DESCRICAO', 'LISTA_PRESENCA', 'TIPO']
        for col in cols_txt:
            if col in df.columns:
                # Converte para string, remove 'nan' e espaços
                df[col] = df[col].astype(str).replace('nan', '').str.strip()

        print(f"  ✓ {nome_arquivo}: {len(df):,} linhas processadas.")
        return df

    except Exception as e:
        print(f"  ERRO CRÍTICO ao ler planilha: {e}")
        return pd.DataFrame()

def salvar_banco(df):
    if df.empty: return
    
    print(f"\n--- SALVANDO NO BANCO ({len(df):,} registros) ---")
    
    try:
        with engine_principal.connect() as conn:
            # 1. Recria a tabela limpa
            conn.execute(text("DROP TABLE IF EXISTS capacitacoes"))
            
            sql_create = """
            CREATE TABLE capacitacoes (
                id INT AUTO_INCREMENT PRIMARY KEY,
                ORDEM INT,
                DATA_CAPACITACAO DATE,
                DESCRICAO TEXT,
                LISTA_PRESENCA VARCHAR(50),
                QTD_PARTICIPANTES INT DEFAULT 0,
                TIPO VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_data (DATA_CAPACITACAO)
            );
            """
            conn.execute(text(sql_create))
            conn.commit()
        
        # 2. Salva em Paralelo
        num_workers = max(1, os.cpu_count() - 1)
        chunk = math.ceil(len(df) / num_workers)
        chunks = [df[i:i + chunk] for i in range(0, len(df), chunk)]
        
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            list(executor.map(worker_salvar_chunk, chunks))
            
        print("  ✓ SUCESSO! Tabela 'capacitacoes' recriada e populada.")

    except Exception as e:
        print(f"  ERRO CRÍTICO DE BANCO: {e}")

if __name__ == "__main__":
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    PLANILHAS = os.path.join(os.path.dirname(BASE_DIR), 'Planilhas')
    
    df_final = processar_capacitacoes(PLANILHAS)
    salvar_banco(df_final)