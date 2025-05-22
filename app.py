from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException
import mysql.connector
from mysql.connector import Error
import time
import re
import json
import os

# Carrega configurações do VSCode
def load_vscode_settings():
    settings_path = os.path.join(os.getcwd(), '.vscode', 'settings.json')
    try:
        with open(settings_path) as f:
            settings = json.load(f)
            return settings['sqltools.connections'][0]
    except Exception as e:
        print(f"⚠️ Não foi possível carregar configurações do VSCode: {e}")
        return None

# Configuração do navegador
options = webdriver.ChromeOptions()
options.add_argument("--disable-blink-features=AutomationControlled")
driver = webdriver.Chrome(options=options)
driver.get('https://ctiimobiliaria.com.br')
driver.maximize_window()

class DatabaseManager:
    def __init__(self):
        self.connection = None
        config = load_vscode_settings() or {
            'server': 'DB_HOST',
            'port': 'DB_PORT',
            'database': 'DB_USER',
            'username': 'DB_NAME',
            'password': 'DB_PASSWORD'
        }
        
        try:
            self.connection = mysql.connector.connect(
                host=config['server'],
                port=config['port'],
                database=config['database'],
                user=config['username'],
                password=config.get('password', 'root'),
                charset='utf8mb4'
            )
            print("✅ Conexão MySQL estabelecida usando configurações do VSCode")
        except Error as e:
            print(f"❌ Falha na conexão MySQL: {e}")
            raise

    def _execute_query(self, query, params=None, fetch=False):
        cursor = self.connection.cursor(dictionary=True)
        try:
            cursor.execute(query, params)
            if fetch:
                return cursor.fetchall()
            self.connection.commit()
            return True
        except Error as e:
            print(f"❌ Erro na query: {e}")
            return False
        finally:
            cursor.close()

    def inserir_imovel(self, dados):
        try:
            bairro_id = self._get_bairro_id(dados.get('bairro', 'Recife'))
            if not bairro_id:
                raise ValueError("Bairro não encontrado/criado")

            dados_completos = {
                'codigo': dados.get('codigo', None),
                'titulo': dados.get('titulo', 'Sem título')[:200],
                'descricao': f"{dados.get('quartos', 0)} quartos, {dados.get('vagas', 0)} vagas em {dados.get('bairro', 'Recife')}",
                'preco': float(dados.get('preco', 0)),
                'area_total': float(dados.get('area', 0)),
                'area_util': float(dados.get('area', 0)),
                'quartos': int(dados.get('quartos', 0)),
                'suites': int('suíte' in dados.get('titulo', '').lower()),
                'vagas': int(dados.get('vagas', 0)),
                'bairro_id': bairro_id,
                'finalidade_id': 1,  # Alugar
                'tipo_id': 1
            }

            query = """
            INSERT INTO imoveis 
            (codigo, titulo, descricao, preco, area_total, area_util, 
            quartos, suites, vagas, bairro_id, finalidade_id, tipo_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            return self._execute_query(query, tuple(dados_completos.values()))
        
        except Exception as e:
            print(f"⚠️ Erro ao preparar dados: {e}")
            return False

    def _get_bairro_id(self, nome_bairro):
        nome_bairro = nome_bairro.split('|')[0].strip() if '|' in nome_bairro else nome_bairro.strip()
        
        result = self._execute_query(
            "SELECT id FROM bairros WHERE nome = %s", 
            (nome_bairro,), 
            fetch=True
        )
        
        if result:
            return result[0]['id']
        
        # Insere novo bairro e retorna o ID
        cursor = self.connection.cursor()
        cursor.execute(
            "INSERT INTO bairros (nome, cidade_id) VALUES (%s, 1)", 
            (nome_bairro,)
        )
        self.connection.commit()
        return cursor.lastrowid

    def fechar_conexao(self):
        if self.connection and self.connection.is_connected():
            self.connection.close()

def extrair_dados_do_site():
    dados = []
    try:
        print("🔍 Configurando busca...")

        # Define busca inicial
        Select(WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, 'finalidade'))
        )).select_by_value('1')
        time.sleep(2)

        # Tipo: Apartamento
        try:
            Select(driver.find_element(By.ID, 'tipo')).select_by_visible_text('Apartamento')
        except:
            driver.find_element(By.ID, 'tipo').click()
            time.sleep(1)
            driver.find_element(By.XPATH, "//option[contains(., 'Apartamento')]").click()
        time.sleep(2)

        # Local: Recife
        endereco = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, 'endereco'))
        )
        endereco.clear()
        endereco.send_keys("Recife")
        time.sleep(3)

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//li[contains(., 'Recife')]"))
        ).click()
        time.sleep(2)

        # Submete busca
        driver.find_element(By.ID, 'submit-busca').click()
        time.sleep(5)

        print("✅ Página de resultados carregada")

        # Loop de paginação
        while True:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".card"))
            )
            cards = driver.find_elements(By.CSS_SELECTOR, "div.col-xl-3")
            print(f"🔍 {len(cards)} cards nesta página")

            for card in cards:
                try:
                    codigo_element = card.find_element(By.CSS_SELECTOR, ".preco-cond-card")
                    codigo = re.search(r'\d+', codigo_element.text).group()

                    local_element = WebDriverWait(card, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, ".card-body .container-endereco .card-text"))
                    )
                    bairro = local_element.text.split("|")[0].strip()

                    preco_text = card.find_element(By.CSS_SELECTOR, ".preco-imovel-card").text
                    preco = re.sub(r'[^\d,]', '', preco_text).replace(',', '.')

                    caracteristicas = card.find_elements(By.CSS_SELECTOR, ".container-icon span")
                    area = re.sub(r'[^\d,]', '', caracteristicas[0].text).replace(',', '.') if len(caracteristicas) > 0 else '0'
                    quartos = re.search(r'\d+', caracteristicas[1].text).group() if len(caracteristicas) > 1 else '0'
                    vagas = re.search(r'\d+', caracteristicas[2].text).group() if len(caracteristicas) > 2 else '0'

                    dados.append({
                        'codigo': codigo,
                        'titulo': f"Apartamento {quartos} quartos {bairro}",
                        'preco': preco,
                        'bairro': bairro,
                        'area': area,
                        'quartos': quartos,
                        'vagas': vagas
                    })

                    print(f"✅ Extraído: {bairro} | R$ {preco} | {area}m² | {quartos}q | {vagas}v")

                except Exception as e:
                    print(f"⚠️ Erro ao processar card: {str(e)[:100]}...")
                    continue

            # Tenta clicar na próxima página, se existir
            try:
                pagina_atual = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".container-paginacao .btn-paginacao.active"))
                )
                proximo_pagina = pagina_atual.find_element(By.XPATH, "following-sibling::div[1]")

                driver.execute_script("arguments[0].click();", proximo_pagina)
                print("➡️ Avançando para próxima página...")
                time.sleep(3)

            except Exception:
                print("⛔ Nenhuma próxima página encontrada. Finalizando paginação...")
                break

    except Exception as e:
        print(f"❌ Erro na configuração inicial da busca: {e}")

    return dados

def main():
    db = DatabaseManager()
    
    try:
        print("🚀 Iniciando extração de dados...")
        dados = extrair_dados_do_site()
        
        if dados:
            print(f"📊 Total de imóveis encontrados: {len(dados)}")
            for i, imovel in enumerate(dados, 1):
                print(f"🔄 Processando imóvel {i}/{len(dados)}: {imovel['titulo'][:50]}...")
                if not db.inserir_imovel(imovel):
                    print(f"⏭️ Pulando imóvel {i} devido a erro")
                time.sleep(0.5)
            
            print("✅ Todos os dados foram processados!")
        else:
            print("❌ Nenhum dado foi extraído")
            
    except Exception as e:
        print(f"🔥 Erro fatal: {e}")
    finally:
        driver.quit()  # fecha o navegador
        db.fechar_conexao()  # fecha conexão com banco
        print("🔌 Conexões encerradas")

if __name__ == "__main__":
    main()
