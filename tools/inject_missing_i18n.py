#!/usr/bin/env python3
"""Inject missing download/platform translations into all 6 non-EN language blocks"""
import re

with open("docs/index.html", "r", encoding="utf-8") as f:
    html = f.read()

# Define translations for missing keys per language
translations = {
    "zh": {
        "plat_linux": "\U0001f427 Linux",
        "plat_macos": "\U0001f34e macOS",
        "plat_windows": "\U0001fa9f Windows",
        "install_title": "下载与安装",
        "linux_desc": "源码安装 · pip · venv · PEP 668 兼容",
        "mac_desc": "DMG 安装包 · ARM64 原生 · Homebrew",
        "win_desc": "NSIS 安装器 · 7种语言 · 一键安装",
        "win_dl_installer": "\U0001f4e6 下载安装版",
        "win_dl_portable": "\U0001f4c2 下载便携版",
        "mac_dl": "\U0001f4e5 下载 DMG",
        "win_title": "\U0001fa9f Windows 桌面客户端",
        "win_installer_title": "一键安装",
        "win_installer_desc": "NSIS 安装器(7语言) · 开始菜单快捷方式 · 添加/删除程序",
        "win_download_installer": "下载安装版",
        "win_portable_title": "便携版",
        "win_portable_desc": "无需安装 · 解压即用 · 自包含运行时",
        "win_download_portable": "下载便携版",
        "win_macos_title": "macOS",
        "win_macos_desc": "DMG 安装包 · ARM64 原生支持",
        "win_download_macos": "下载 macOS 版",
    },
    "ja": {
        "plat_linux": "\U0001f427 Linux",
        "plat_macos": "\U0001f34e macOS",
        "plat_windows": "\U0001fa9f Windows",
        "install_title": "ダウンロードとインストール",
        "linux_desc": "ソースインストール · pip · venv · PEP 668 互換",
        "mac_desc": "DMG パッケージ · ARM64 ネイティブ · Homebrew",
        "win_desc": "NSIS インストーラー · 7言語 · ワンクリック",
        "win_dl_installer": "\U0001f4e6 インストーラーをダウンロード",
        "win_dl_portable": "\U0001f4c2 ポータブル版をダウンロード",
        "mac_dl": "\U0001f4e5 DMG をダウンロード",
        "win_title": "\U0001fa9f Windows デスクトップクライアント",
        "win_installer_title": "ワンクリックインストール",
        "win_installer_desc": "NSIS インストーラー(7言語) · スタートメニュー · プログラムの追加と削除",
        "win_download_installer": "インストーラーをダウンロード",
        "win_portable_title": "ポータブル版",
        "win_portable_desc": "インストール不要 · 解凍するだけ · 自己完結型ランタイム",
        "win_download_portable": "ポータブル版をダウンロード",
        "win_macos_title": "macOS",
        "win_macos_desc": "DMG パッケージ · ARM64 ネイティブ対応",
        "win_download_macos": "macOS 版をダウンロード",
        "plugin_title": "\U0001f50c プラグインマーケットプレイス",
        "plugin_subtitle": "コミュニティ主導 · MCP ネイティブ · GitHub ホスト · ワンクリックインストール",
    },
    "ko": {
        "plat_linux": "\U0001f427 Linux",
        "plat_macos": "\U0001f34e macOS",
        "plat_windows": "\U0001fa9f Windows",
        "install_title": "다운로드 및 설치",
        "linux_desc": "소스 설치 · pip · venv · PEP 668 호환",
        "mac_desc": "DMG 패키지 · ARM64 네이티브 · Homebrew",
        "win_desc": "NSIS 설치 프로그램 · 7개 언어 · 원클릭",
        "win_dl_installer": "\U0001f4e6 설치 프로그램 다운로드",
        "win_dl_portable": "\U0001f4c2 포터블 버전 다운로드",
        "mac_dl": "\U0001f4e5 DMG 다운로드",
        "win_title": "\U0001fa9f Windows 데스크톱 클라이언트",
        "win_installer_title": "원클릭 설치",
        "win_installer_desc": "NSIS 설치 프로그램(7개 언어) · 시작 메뉴 바로가기 · 프로그램 추가/제거",
        "win_download_installer": "설치 프로그램 다운로드",
        "win_portable_title": "포터블 버전",
        "win_portable_desc": "설치 불필요 · 압축 해제 후 실행 · 자체 포함 런타임",
        "win_download_portable": "포터블 버전 다운로드",
        "win_macos_title": "macOS",
        "win_macos_desc": "DMG 패키지 · ARM64 네이티브 지원",
        "win_download_macos": "macOS 버전 다운로드",
        "plugin_title": "\U0001f50c 플러그인 마켓플레이스",
        "plugin_subtitle": "커뮤니티 주도 · MCP 네이티브 · GitHub 호스팅 · 원클릭 설치",
    },
    "de": {
        "plat_linux": "\U0001f427 Linux",
        "plat_macos": "\U0001f34e macOS",
        "plat_windows": "\U0001fa9f Windows",
        "install_title": "Herunterladen & Installieren",
        "linux_desc": "Quellinstallation · pip · venv · PEP 668 kompatibel",
        "mac_desc": "DMG-Paket · ARM64-nativ · Homebrew",
        "win_desc": "NSIS-Installer · 7 Sprachen · Ein-Klick",
        "win_dl_installer": "\U0001f4e6 Installer herunterladen",
        "win_dl_portable": "\U0001f4c2 Portable Version herunterladen",
        "mac_dl": "\U0001f4e5 DMG herunterladen",
        "win_title": "\U0001fa9f Windows Desktop Client",
        "win_installer_title": "Ein-Klick-Installation",
        "win_installer_desc": "NSIS-Installer (7 Sprachen) · Startmenü-Verknüpfung · Programme hinzufügen/entfernen",
        "win_download_installer": "Installer herunterladen",
        "win_portable_title": "Portable Edition",
        "win_portable_desc": "Keine Installation nötig · Entpacken & ausführen · Eigenständige Laufzeitumgebung",
        "win_download_portable": "Portable Version herunterladen",
        "win_macos_title": "macOS",
        "win_macos_desc": "DMG-Paket · Native ARM64-Unterstützung",
        "win_download_macos": "Für macOS herunterladen",
        "plugin_title": "\U0001f50c Plugin-Marktplatz",
        "plugin_subtitle": "Community-getrieben · MCP-nativ · GitHub-gehostet · Ein-Klick-Installation",
    },
    "fr": {
        "plat_linux": "\U0001f427 Linux",
        "plat_macos": "\U0001f34e macOS",
        "plat_windows": "\U0001fa9f Windows",
        "install_title": "Télécharger & Installer",
        "linux_desc": "Installation source · pip · venv · Compatible PEP 668",
        "mac_desc": "Paquet DMG · ARM64 natif · Homebrew",
        "win_desc": "Installateur NSIS · 7 langues · Un clic",
        "win_dl_installer": "\U0001f4e6 Télécharger l'installateur",
        "win_dl_portable": "\U0001f4c2 Télécharger la version portable",
        "mac_dl": "\U0001f4e5 Télécharger le DMG",
        "win_title": "\U0001fa9f Client Bureau Windows",
        "win_installer_title": "Installation en un clic",
        "win_installer_desc": "Installateur NSIS (7 langues) · Raccourci menu Démarrer · Ajout/Suppression de programmes",
        "win_download_installer": "Télécharger l'installateur",
        "win_portable_title": "Édition Portable",
        "win_portable_desc": "Aucune installation · Extraire & exécuter · Runtime autonome",
        "win_download_portable": "Télécharger la version portable",
        "win_macos_title": "macOS",
        "win_macos_desc": "Paquet DMG · Support ARM64 natif",
        "win_download_macos": "Télécharger pour macOS",
        "plugin_title": "\U0001f50c Marché de Plugins",
        "plugin_subtitle": "Piloté par la communauté · MCP natif · Hébergé sur GitHub · Installation en un clic",
    },
    "es": {
        "plat_linux": "\U0001f427 Linux",
        "plat_macos": "\U0001f34e macOS",
        "plat_windows": "\U0001fa9f Windows",
        "install_title": "Descargar e Instalar",
        "linux_desc": "Instalación desde código · pip · venv · Compatible PEP 668",
        "mac_desc": "Paquete DMG · ARM64 nativo · Homebrew",
        "win_desc": "Instalador NSIS · 7 idiomas · Un clic",
        "win_dl_installer": "\U0001f4e6 Descargar Instalador",
        "win_dl_portable": "\U0001f4c2 Descargar Versión Portátil",
        "mac_dl": "\U0001f4e5 Descargar DMG",
        "win_title": "\U0001fa9f Cliente de Escritorio Windows",
        "win_installer_title": "Instalación en un clic",
        "win_installer_desc": "Instalador NSIS (7 idiomas) · Acceso directo en Menú Inicio · Agregar/Quitar Programas",
        "win_download_installer": "Descargar Instalador",
        "win_portable_title": "Edición Portátil",
        "win_portable_desc": "Sin instalación · Extraer y ejecutar · Runtime autónomo",
        "win_download_portable": "Descargar Versión Portátil",
        "win_macos_title": "macOS",
        "win_macos_desc": "Paquete DMG · Soporte ARM64 nativo",
        "win_download_macos": "Descargar para macOS",
        "plugin_title": "\U0001f50c Mercado de Plugins",
        "plugin_subtitle": "Impulsado por la comunidad · MCP nativo · Alojado en GitHub · Instalación en un clic",
    },
}

changes = 0
for lang, keys in translations.items():
    # Find the lang block start: "lang: {"
    pattern = lang + ':\\s*\\{'
    m = re.search(pattern, html)
    if not m:
        print(f"WARNING: {lang} block not found")
        continue
    
    block_start = m.end()
    
    # Find matching closing brace
    depth = 1
    i = block_start
    while i < len(html) and depth > 0:
        if html[i] == '{':
            depth += 1
        elif html[i] == '}':
            depth -= 1
        i += 1
    
    block_end = i - 1  # position of closing }
    block_content = html[block_start:block_end]
    
    # Build insertion string for missing keys
    insert_parts = []
    for key, val in keys.items():
        if key + ':' in block_content:
            continue  # already exists
        # Escape backslashes and quotes in values
        escaped_val = val.replace('\\', '\\\\').replace('"', '\\"')
        insert_parts.append(key + ':"' + escaped_val + '"')
    
    if not insert_parts:
        print(f"{lang}: all keys already present, skipping")
        continue
    
    insert_str = "," + ",".join(insert_parts)
    
    # Insert before closing brace
    html = html[:block_end] + insert_str + html[block_end:]
    changes += len(insert_parts)
    print(f"{lang}: added {len(insert_parts)} keys")

with open("docs/index.html", "w", encoding="utf-8") as f:
    f.write(html)

print(f"\nTotal: {changes} keys added across all languages")
