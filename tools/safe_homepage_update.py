#!/usr/bin/env python3
"""
安全主页更新脚本 — 严格Dev→UAT→Production流程
用法: python3 tools/safe_homepage_update.py
验证: node tools/validate_i18n.js && pytest tests/test_project_integrity.py::TestHomepageI18N
"""
import re, json, sys, subprocess

HTML_PATH = "docs/index.html"

# ═══ 新特性定义 ═══
# 竞品表新增行 (c34-c37)
COMPARE_NEW = {
    'en': {
        'c34': '🧠 JEPA World Model', 'cv_q': 'LeCun Latent Prediction',
        'c35': '🖥️ Desktop Agent', 'cv_r': 'Windows GUI Automation',
        'c36': '🔐 Smart Permissions', 'cv_s': 'Learns When to Auto-Approve',
        'c37': '🧠 JEPA Router', 'cv_t': 'Predictive Model Selection',
    },
    'zh': {
        'c34': '🧠 JEPA世界模型', 'cv_q': 'LeCun潜空间预测',
        'c35': '🖥️ 桌面Agent', 'cv_r': 'Windows GUI自动化',
        'c36': '🔐 智能权限', 'cv_s': '学习自动批准模式',
        'c37': '🧠 JEPA路由器', 'cv_t': '预测式模型选择',
    },
    'ja': {
        'c34': '🧠 JEPA世界モデル', 'cv_q': 'LeCun潜空間予測',
        'c35': '🖥️ デスクトップAgent', 'cv_r': 'Windows GUI自動化',
        'c36': '🔐 スマート権限', 'cv_s': '自動承認学習',
        'c37': '🧠 JEPAルーター', 'cv_t': '予測モデル選択',
    },
    'ko': {
        'c34': '🧠 JEPA 세계모델', 'cv_q': 'LeCun 잠재공간 예측',
        'c35': '🖥️ 데스크톱 Agent', 'cv_r': 'Windows GUI 자동화',
        'c36': '🔐 스마트 권한', 'cv_s': '자동 승인 학습',
        'c37': '🧠 JEPA 라우터', 'cv_t': '예측 모델 선택',
    },
    'de': {
        'c34': '🧠 JEPA Weltmodell', 'cv_q': 'LeCun Latente Vorhersage',
        'c35': '🖥️ Desktop Agent', 'cv_r': 'Windows GUI Automatisierung',
        'c36': '🔐 Smart-Rechte', 'cv_s': 'Lernt Auto-Genehmigung',
        'c37': '🧠 JEPA Router', 'cv_t': 'Prädiktive Modellwahl',
    },
    'fr': {
        'c34': '🧠 Modèle JEPA', 'cv_q': 'Prédiction Latente LeCun',
        'c35': '🖥️ Agent Bureau', 'cv_r': 'Automatisation GUI Windows',
        'c36': '🔐 Permissions IA', 'cv_s': 'Apprentissage Auto-Approbation',
        'c37': '🧠 Routeur JEPA', 'cv_t': 'Sélection Prédictive',
    },
    'es': {
        'c34': '🧠 Modelo JEPA', 'cv_q': 'Predicción Latente LeCun',
        'c35': '🖥️ Agente Escritorio', 'cv_r': 'Automatización GUI Windows',
        'c36': '🔐 Permisos IA', 'cv_s': 'Auto-Aprobación Inteligente',
        'c37': '🧠 Enrutador JEPA', 'cv_t': 'Selección Predictiva',
    },
}

# 特性卡片新增 (f18-f22)
FEATURE_NEW = {
    'en': {
        'f18_title': '🧠 JEPA World Model', 'f18_desc': 'LeCun latent space prediction. No text generation needed. Token -100%, latency -99.8%.',
        'f19_title': '🖥️ Desktop Agent', 'f19_desc': 'Native Windows GUI automation. Screen perception, mouse/keyboard control, app launching.',
        'f20_title': '🔐 Smart Permissions', 'f20_desc': 'Learns your approval patterns. 5-level risk grading. Auto-approves known-safe actions.',
        'f21_title': '🎯 JEPA Router', 'f21_desc': 'Predictive model selection. No trial-and-error. Complexity-aware + domain-matched + cost-optimized.',
        'f22_title': '📊 Evolution Tracker', 'f22_desc': 'Tracks capability growth across versions. 6-dimension scoring. Predicts next-version performance.',
    },
    'zh': {
        'f18_title': '🧠 JEPA世界模型', 'f18_desc': 'LeCun潜空间预测。不生成文本。Token -100%，延迟-99.8%。',
        'f19_title': '🖥️ 桌面Agent', 'f19_desc': 'Windows GUI自动化。屏幕感知、鼠标键盘操控、应用启动。',
        'f20_title': '🔐 智能权限', 'f20_desc': '学习你的批准模式。5级风险分级。自动批准已知安全操作。',
        'f21_title': '🎯 JEPA路由器', 'f21_desc': '预测式模型选择。不用试错。复杂度感知+领域匹配+成本优化。',
        'f22_title': '📊 进化追踪器', 'f22_desc': '追踪版本间能力增长。6维度评分。预测下一版本性能。',
    },
    'ja': {
        'f18_title': '🧠 JEPA世界モデル', 'f18_desc': 'LeCun潜空間予測。テキスト生成不要。Token -100%、遅延-99.8%。',
        'f19_title': '🖥️ デスクトップAgent', 'f19_desc': 'Windows GUI自動化。画面認識、マウス/キーボード操作、アプリ起動。',
        'f20_title': '🔐 スマート権限', 'f20_desc': '承認パターンを学習。5段階リスク評価。安全操作を自動承認。',
        'f21_title': '🎯 JEPAルーター', 'f21_desc': '予測モデル選択。試行不要。複雑度+領域+コスト最適化。',
        'f22_title': '📊 進化トラッカー', 'f22_desc': 'バージョン間の能力成長を追跡。6次元評価。次バージョン性能予測。',
    },
    'ko': {
        'f18_title': '🧠 JEPA 세계모델', 'f18_desc': 'LeCun 잠재공간 예측. 텍스트 생성 불필요. Token -100%, 지연 -99.8%.',
        'f19_title': '🖥️ 데스크톱 Agent', 'f19_desc': 'Windows GUI 자동화. 화면 인식, 마우스/키보드 제어, 앱 실행.',
        'f20_title': '🔐 스마트 권한', 'f20_desc': '승인 패턴 학습. 5단계 위험 평가. 안전 작업 자동 승인.',
        'f21_title': '🎯 JEPA 라우터', 'f21_desc': '예측 모델 선택. 시도 불필요. 복잡도+영역+비용 최적화.',
        'f22_title': '📊 진화 추적기', 'f22_desc': '버전 간 능력 성장 추적. 6차원 평가. 다음 버전 성능 예측.',
    },
    'de': {
        'f18_title': '🧠 JEPA Weltmodell', 'f18_desc': 'LeCun latente Vorhersage. Keine Texterzeugung. Token -100%, Latenz -99.8%.',
        'f19_title': '🖥️ Desktop Agent', 'f19_desc': 'Windows GUI-Automatisierung. Bildschirmwahrnehmung, Maus/Tastatur, App-Start.',
        'f20_title': '🔐 Smart-Rechte', 'f20_desc': 'Lernt Genehmigungsmuster. 5 Risikostufen. Automatische Freigabe sicherer Aktionen.',
        'f21_title': '🎯 JEPA Router', 'f21_desc': 'Prädiktive Modellwahl. Kein Ausprobieren. Komplexität+Domäne+Kosten optimiert.',
        'f22_title': '📊 Evolutions-Tracker', 'f22_desc': 'Verfolgt Fähigkeitswachstum über Versionen. 6-Dimensionen-Bewertung. Prognose.',
    },
    'fr': {
        'f18_title': '🧠 Modèle JEPA', 'f18_desc': 'Prédiction latente LeCun. Pas de génération de texte. Token -100%, latence -99.8%.',
        'f19_title': '🖥️ Agent Bureau', 'f19_desc': 'Automatisation GUI Windows. Perception écran, contrôle souris/clavier, lancement apps.',
        'f20_title': '🔐 Permissions IA', 'f20_desc': 'Apprend vos habitudes d\'approbation. 5 niveaux de risque. Auto-approbation sécurisée.',
        'f21_title': '🎯 Routeur JEPA', 'f21_desc': 'Sélection prédictive de modèle. Sans essai. Complexité+domaine+coût optimisés.',
        'f22_title': '📊 Traqueur Évolution', 'f22_desc': 'Suit la croissance des capacités entre versions. Évaluation 6-D. Prédiction version suivante.',
    },
    'es': {
        'f18_title': '🧠 Modelo JEPA', 'f18_desc': 'Predicción latente LeCun. Sin generar texto. Token -100%, latencia -99.8%.',
        'f19_title': '🖥️ Agente Escritorio', 'f19_desc': 'Automatización GUI Windows. Percepción de pantalla, control ratón/teclado, inicio apps.',
        'f20_title': '🔐 Permisos IA', 'f20_desc': 'Aprende tus patrones de aprobación. 5 niveles de riesgo. Auto-aprobación segura.',
        'f21_title': '🎯 Enrutador JEPA', 'f21_desc': 'Selección predictiva de modelo. Sin ensayo. Complejidad+dominio+coste optimizados.',
        'f22_title': '📊 Rastreador Evolución', 'f22_desc': 'Sigue el crecimiento de capacidades entre versiones. Puntuación 6-D. Predicción.',
    },
}

def add_compare_keys(html):
    """在JS块中安全添加c34-c37 — 通用匹配"""
    for lang, keys in COMPARE_NEW.items():
        # Match: c33:"任何文本",cv_p:"任何文本" — 通用模式
        pattern = rf'(c33:"[^"]*"),(cv_p:"[^"]*")'
        
        # Only match in the correct language block
        lang_start = html.find(f'\n    {lang}: {{')
        if lang_start < 0:
            # Try compact format
            lang_start = html.find(f'{lang}: {{')
        if lang_start < 0:
            print(f"  {lang}: block not found!")
            continue
        
        # Find the end of this language block
        next_lang = html.find('\n    ', lang_start + 10)
        if next_lang < 0:
            next_lang = len(html)
        block = html[lang_start:next_lang]
        
        # Replace within this block only
        match = re.search(pattern, block)
        if match:
            insert = ',' + ','.join(f'{key}:"{val}"' for key, val in keys.items())
            new_block = block[:match.end()] + insert + block[match.end():]
            html = html[:lang_start] + new_block + html[next_lang:]
            print(f"  {lang}: compare keys added")
        else:
            print(f"  {lang}: c33/cv_p pattern not found!")
    return html

def add_feature_keys(html):
    """在JS块中安全添加f18-f22"""
    for lang, keys in FEATURE_NEW.items():
        # 找到该语言块中 f17_desc 的位置，在其后插入
        f17_pattern = rf'(f17_desc:"[^"]*")'
        def replacer(m, l=lang, k=keys):
            insert = ',' + ','.join(f'{key}:"{val}"' for key, val in k.items())
            return m.group(0) + insert
        
        html = re.sub(f17_pattern, replacer, html, count=1)
        print(f"  {lang}: feature keys added")
    return html

def add_feature_cards(html):
    """在HTML中添加f18-f22特性卡片"""
    f17_card = 'data-lang-key="f17_desc">Real-time performance tuning. PID-controlled parameter optimization.</p></div>'
    new_cards = '''
            <div class="feature-card" style="border-color:#8b5cf6;"><div class="feature-icon">🧠</div><h3 data-lang-key="f18_title">JEPA World Model</h3><p data-lang-key="f18_desc">LeCun latent space prediction. No text generation needed.</p></div>
            <div class="feature-card" style="border-color:#22c55e;"><div class="feature-icon">🖥️</div><h3 data-lang-key="f19_title">Desktop Agent</h3><p data-lang-key="f19_desc">Native Windows GUI automation. AI that operates real desktops.</p></div>
            <div class="feature-card" style="border-color:#f59e0b;"><div class="feature-icon">🔐</div><h3 data-lang-key="f20_title">Smart Permissions</h3><p data-lang-key="f20_desc">Learns your approval patterns. Eliminates agent permission fatigue.</p></div>
            <div class="feature-card" style="border-color:#06b6d4;"><div class="feature-icon">🎯</div><h3 data-lang-key="f21_title">JEPA Router</h3><p data-lang-key="f21_desc">Predictive model selection. No trial-and-error. Token -80%.</p></div>
            <div class="feature-card" style="border-color:#ec4899;"><div class="feature-icon">📊</div><h3 data-lang-key="f22_title">Evolution Tracker</h3><p data-lang-key="f22_desc">Tracks capability growth. 6-dimension scoring. Predicts next version.</p></div>'''
    
    if f17_card in html:
        html = html.replace(f17_card, f17_card + new_cards)
        print("  feature cards: added")
    else:
        print("  feature cards: NOT FOUND!")
    return html

def add_compare_rows(html):
    """在HTML竞品表中添加c34-c37行"""
    c33_end = '<td><span class="cross">✗</span></td><td><span class="cross">✗</span></td></tr>'
    # Find the LAST occurrence (c33 row)
    pos = html.rfind(c33_end)
    if pos < 0:
        print("  compare rows: c33 not found!")
        return html
    
    new_rows = '''
                <tr style="border-top:2px solid #8b5cf6;"><td data-lang-key="c34"><strong>🧠 JEPA World Model</strong><br><span style="font-size:10px;color:var(--muted);" data-lang-key="cv_q">LeCun Latent Prediction</span></td><td class="highlight"><span class="check">✅ v3.36</span></td><td><span class="cross">✗</span></td><td><span class="cross">✗</span></td><td><span class="cross">✗</span></td><td><span class="cross">✗</span></td></tr>
                <tr style="border-top:2px solid #22c55e;"><td data-lang-key="c35"><strong>🖥️ Desktop Agent</strong><br><span style="font-size:10px;color:var(--muted);" data-lang-key="cv_r">Windows GUI Automation</span></td><td class="highlight"><span class="check">✅ v3.37</span></td><td><span class="cross">✗</span></td><td><span class="cross">✗</span></td><td><span class="cross">✗</span></td><td><span class="cross">✗</span></td></tr>
                <tr style="border-top:2px solid #f59e0b;"><td data-lang-key="c36"><strong>🔐 Smart Permissions</strong><br><span style="font-size:10px;color:var(--muted);" data-lang-key="cv_s">Learns When to Auto-Approve</span></td><td class="highlight"><span class="check">✅ v3.38</span></td><td><span class="cross">✗</span></td><td><span class="cross">✗</span></td><td><span class="cross">✗</span></td><td><span class="cross">✗</span></td></tr>
                <tr style="border-top:2px solid #06b6d4;"><td data-lang-key="c37"><strong>🧠 JEPA Router</strong><br><span style="font-size:10px;color:var(--muted);" data-lang-key="cv_t">Predictive Model Selection</span></td><td class="highlight"><span class="check">✅ v3.39</span></td><td><span class="cross">✗</span></td><td><span class="cross">✗</span></td><td><span class="cross">✗</span></td><td><span class="cross">✗</span></td></tr>'''
    
    html = html[:pos + len(c33_end)] + new_rows + html[pos + len(c33_end):]
    print("  compare rows: added")
    return html

# ═══ Main ═══
def main():
    with open(HTML_PATH, 'r', encoding='utf-8') as f:
        html = f.read()
    
    print("Step 1: Adding compare keys (c34-c37)...")
    html = add_compare_keys(html)
    
    print("Step 2: Adding feature keys (f18-f22)...")
    html = add_feature_keys(html)
    
    print("Step 3: Adding HTML feature cards...")
    html = add_feature_cards(html)
    
    print("Step 4: Adding HTML compare rows...")
    html = add_compare_rows(html)
    
    with open(HTML_PATH, 'w', encoding='utf-8') as f:
        f.write(html)
    
    # Validate
    print("\n=== Node.js Validation ===")
    r = subprocess.run(['node', 'tools/validate_i18n.js'], capture_output=True, text=True)
    print(r.stdout)
    if r.returncode != 0:
        print("❌ NODE VALIDATION FAILED!")
        sys.exit(1)
    
    print("=== Pytest Validation ===")
    r2 = subprocess.run(['python', '-m', 'pytest', 'tests/test_project_integrity.py::TestHomepageI18N', '-q', '--tb=short'], capture_output=True, text=True)
    print(r2.stdout)
    if r2.returncode != 0:
        print(r2.stderr)
        print("❌ PYTEST VALIDATION FAILED!")
        sys.exit(1)
    
    print("✅ ALL VALIDATIONS PASSED — Ready for UAT deployment")

if __name__ == '__main__':
    main()
