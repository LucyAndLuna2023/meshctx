#!/usr/bin/env python3
"""主页发布流程 — 自动同步+验证脚本
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
解决主页bug复发: 新键自动注入7语言+预发布验证
"""
import re, json, sys
from pathlib import Path

HTML_FILE = Path(__file__).parent / "docs" / "index.html"

# 7语言翻译表: 新键→各语言翻译
NEW_TRANSLATIONS = {
    "c23": {
        "en": "🔬 Causal Root Cause (Pearl)", "zh": "🔬 因果根因分析(Pearl)",
        "ja": "🔬 因果ルート原因(Pearl)", "ko": "🔬 인과 근본 원인(Pearl)",
        "de": "🔬 Kausale Ursachenanalyse", "fr": "🔬 Analyse Causale (Pearl)",
        "es": "🔬 Causa Raíz Causal (Pearl)",
    },
    "c24": {
        "en": "🔒 Prompt Injection Shield", "zh": "🔒 Prompt注入防护盾",
        "ja": "🔒 プロンプト注入シールド", "ko": "🔒 프롬프트 주입 방어",
        "de": "🔒 Prompt-Injektionsschutz", "fr": "🔒 Bouclier d'Injection",
        "es": "🔒 Escudo de Inyección",
    },
    "c25": {
        "en": "🔍 Cross-Validation", "zh": "🔍 多Agent交叉验证",
        "ja": "🔍 クロス検証", "ko": "🔍 교차 검증",
        "de": "🔍 Kreuzvalidierung", "fr": "🔍 Validation Croisée",
        "es": "🔍 Validación Cruzada",
    },
    "c26": {
        "en": "📋 Behavior Compliance", "zh": "📋 行为合规监控",
        "ja": "📋 行動コンプライアンス", "ko": "📋 행동 규정 준수",
        "de": "📋 Verhaltenskonformität", "fr": "📋 Conformité Comportementale",
        "es": "📋 Cumplimiento de Conducta",
    },
    "c27": {
        "en": "🧮 Info-Geometric Router", "zh": "🧮 信息几何路由器",
        "ja": "🧮 情報幾何ルーター", "ko": "🧮 정보기하 라우터",
        "de": "🧮 Geometrischer Router", "fr": "🧮 Routeur Géo-Info",
        "es": "🧮 Enrutador Geométrico",
    },
    "c28": {
        "en": "🔄 Self-Updater", "zh": "🔄 自主更新引擎",
        "ja": "🔄 自己アップデーター", "ko": "🔄 자가 업데이터",
        "de": "🔄 Selbst-Updater", "fr": "🔄 Auto-Mise-à-Jour",
        "es": "🔄 Auto-Actualizador",
    },
    "c29": {
        "en": "💾 Backup Vault", "zh": "💾 备份保险库",
        "ja": "💾 バックアップ保管庫", "ko": "💾 백업 보관소",
        "de": "💾 Backup-Tresor", "fr": "💾 Coffre de Sauvegarde",
        "es": "💾 Bóveda de Respaldo",
    },
    "c30": {
        "en": "🎯 Goal Decomposer", "zh": "🎯 目标分解引擎",
        "ja": "🎯 ゴール分解", "ko": "🎯 목표 분해기",
        "de": "🎯 Zielzerleger", "fr": "🎯 Décomposeur d'Objectifs",
        "es": "🎯 Descomponedor de Metas",
    },
    "c31": {
        "en": "📚 Error Learner (ALiFE)", "zh": "📚 错误学习引擎(ALiFE)",
        "ja": "📚 エラー学習(ALiFE)", "ko": "📚 오류 학습(ALiFE)",
        "de": "📚 Fehlerlerner (ALiFE)", "fr": "📚 Apprentissage d'Erreurs",
        "es": "📚 Aprendiz de Errores (ALiFE)",
    },
    "c32": {
        "en": "⚡ Workflow Engine", "zh": "⚡ 工作流编排引擎",
        "ja": "⚡ ワークフローエンジン", "ko": "⚡ 워크플로우 엔진",
        "de": "⚡ Workflow-Engine", "fr": "⚡ Moteur de Workflow",
        "es": "⚡ Motor de Flujo de Trabajo",
    },
}


def validate():
    """预发布验证"""
    html = HTML_FILE.read_text(encoding="utf-8")
    errors = []

    # 1. HTML语法
    from html.parser import HTMLParser
    class V(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []
        def handle_starttag(self, tag, attrs):
            if tag not in ('br','hr','img','input','meta','link'): self.stack.append(tag)
        def handle_endtag(self, tag):
            if self.stack and self.stack[-1] == tag: self.stack.pop()
    v = V()
    try:
        v.feed(html)
        if v.stack: errors.append(f"未闭合标签: {v.stack}")
    except Exception as e:
        errors.append(f"HTML解析失败: {e}")

    # 2. 所有data-lang-key在7语言中
    keys = set(re.findall(r'data-lang-key="([^"]+)"', html))
    langs = ['en','zh','ja','ko','de','fr','es']
    
    for lang in langs:
        pattern = rf'{lang}:\s*\{{'
        m = re.search(pattern, html)
        if not m:
            errors.append(f"缺少{lang}语言块")
            continue
        start = m.start()
        depth = 0; end = start
        for i in range(start, len(html)):
            if html[i] == '{': depth += 1
            elif html[i] == '}':
                depth -= 1
                if depth == 0: end = i+1; break
        block = html[start:end]
        for key in keys:
            if key in ('sb_title',): continue
            if key not in block:
                errors.append(f"{lang}块缺少{key}")

    # 3. 版本号一致性
    ver_match = re.findall(r'v(\d+\.\d+)', html)
    if len(set(ver_match)) > 1:
        errors.append(f"版本号不一致: {set(ver_match)}")

    if errors:
        print(f"❌ {len(errors)} 个问题:")
        for e in errors: print(f"  - {e}")
        return False
    print("✅ 主页验证通过")
    return True


def auto_inject_keys():
    """自动注入新键到所有语言块"""
    html = HTML_FILE.read_text(encoding="utf-8")
    langs = ['en','zh','ja','ko','de','fr','es']
    
    for key, trans in NEW_TRANSLATIONS.items():
        # 检查key是否已存在于所有语言块
        all_exist = all(f'"{key}":' in html for _ in [1])  # Just check HTML
        
        if not all_exist:
            # 在第一个语言块(c22之后)注入
            for lang in langs:
                # 找到该语言的c22行之后插入
                pattern = rf'({lang}:\s*\{{.*?c22:"[^"]+"),'
                match = re.search(pattern, html, re.DOTALL)
                if match:
                    insert_pos = match.end(1)
                    new_entry = f',{key}:"{trans[lang]}"'
                    html = html[:insert_pos] + new_entry + html[insert_pos:]
                    print(f"  注入 {key} → {lang}")
    
    HTML_FILE.write_text(html, encoding="utf-8")
    print("自动注入完成")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--inject":
        auto_inject_keys()
    validate()
